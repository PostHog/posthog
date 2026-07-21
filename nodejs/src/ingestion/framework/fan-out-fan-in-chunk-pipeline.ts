import { logger } from '~/common/utils/logger'

import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { InterleavingChunkPipeline, PullOutcome } from './interleaving-chunk-pipeline'
import { PipelineContext, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResultType, isDropResult, isOkResult, ok } from './results'

/**
 * Splits one element into its sub-elements. Must be synchronous and cheap —
 * heavy work belongs in the subpipeline's steps. Passed as a named function
 * (like processing steps) so its `.name` can be used for error attribution.
 */
export type FanOutFunction<TElement, TSub> = (element: TElement) => TSub[]

/**
 * Folds the subpipeline's results back into the original element. Must be
 * synchronous and cheap. Receives the OK sub-results that survived the
 * subpipeline — possibly fewer than were fanned out (excluded sub-elements
 * contribute nothing), possibly none at all.
 */
export type FanInFunction<TElement, TSubOut, TMerged> = (original: TElement, results: TSubOut[]) => TMerged

/**
 * Correlates a sub-element's context back to its parent. A symbol-keyed
 * property survives the `{ ...context }` spreads steps perform, and keeps
 * working when the subpipeline reorders elements (e.g. via
 * `concurrentlyPerGroup`) — index-based correlation would not. The key is
 * module-private; sub contexts are typed as plain `COutput` outwardly.
 */
const FAN_OUT_PARENT = Symbol('fanOutParent')

interface PendingParent<TElement, TSubOut, C> {
    original: TElement
    /** Parent context with its own sideEffects/warnings arrays; sub completions merge into them. */
    context: PipelineContext<C>
    outstanding: number
    collected: TSubOut[]
}

type SubContext<TElement, TSubOut, C> = PipelineContext<C> & {
    [FAN_OUT_PARENT]?: PendingParent<TElement, TSubOut, C>
}

/**
 * A chunk pipeline stage that fans each OK element out into N sub-elements,
 * processes them through a subpipeline (reusing retry, `concurrently`, etc.),
 * and fans the results back into the original element:
 *
 * 1. `fanOutFn(element)` produces the sub-elements; zero sub-elements complete
 *    the parent immediately via `fanInFn(element, [])`.
 * 2. Each sub-element runs through the subpipeline with its own context
 *    (fresh sideEffects/warnings arrays, merged back into the parent when the
 *    sub-result arrives — so nothing is double-counted).
 * 3. When all of a parent's sub-results are in, the parent emits
 *    `ok(fanInFn(original, collected))` — always. Sub-result handling:
 *    - OK contributes its value to `collected`.
 *    - DROP is the sanctioned way for a sub-step to exclude a sub-element:
 *      it contributes nothing, silently — the parent fans in with the
 *      survivors, consistent with a zero-fan-out fanning in with `[]`.
 *    - DLQ and REDIRECT also contribute nothing, but log a warning: they are
 *      almost certainly misuse, since sub-elements are not Kafka messages —
 *      there is nothing to dead-letter or redirect. Route the parent before
 *      fanning out instead.
 *    Side effects and warnings from every sub-result (OK or not) still merge
 *    into the parent context.
 *
 * Cardinality is preserved at the parent level: N parents in, N results out.
 * Sub-element cardinality is fully contained inside the stage — and so are
 * the subpipeline's result types: no sub-result can escape as the parent's
 * result, so the stage emits only the upstream's redirect names (`RPrev`,
 * not `RPrev | RSub`).
 *
 * Ordering: parents emit as their sub-results complete (unordered), the same
 * contract as `concurrentlyPerGroup`. Non-OK parents pass through untouched.
 *
 * Failures poison the stage: if the upstream, `fanOutFn`, `fanInFn`, or the
 * subpipeline throws, results already in flight still drain, then next()
 * rejects with that error permanently (standard {@link InterleavingChunkPipeline}
 * behavior). Retryable failures belong inside the subpipeline via step retry
 * options.
 */
export class FanOutFanInChunkPipeline<
    TInput,
    TElement,
    TSub,
    TSubOut,
    TMerged,
    CInput,
    COutput = CInput,
    RPrev extends string = never,
    RSub extends string = never,
> implements ChunkPipeline<TInput, TMerged, CInput, COutput, RPrev>
{
    private inner: InterleavingChunkPipeline<TInput, TMerged, CInput, COutput, RPrev>
    private pendingParents = new Set<PendingParent<TElement, TSubOut, COutput>>()
    /** Parents completed by sub-results, drained by onProcessPull before pulling the subpipeline again. */
    private readyResults: PipelineResultWithContext<TMerged, COutput, RPrev>[] = []
    private fanOutName: string
    private fanInName: string

    constructor(
        private previousPipeline: ChunkPipeline<TInput, TElement, CInput, COutput, RPrev>,
        private fanOutFn: FanOutFunction<TElement, TSub>,
        private subPipeline: ChunkPipeline<TSub, TSubOut, COutput, COutput, RSub>,
        private fanInFn: FanInFunction<TElement, TSubOut, TMerged>
    ) {
        this.fanOutName = fanOutFn.name || 'anonymousFanOut'
        this.fanInName = fanInFn.name || 'anonymousFanIn'
        this.inner = new InterleavingChunkPipeline<TInput, TMerged, CInput, COutput, RPrev>({
            onFeed: (elements) => this.previousPipeline.feed(elements),
            onSourcePull: () => this.pullAndFanOut(),
            onProcessPull: () => this.drainAndFanIn(),
        })
    }

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.inner.feed(elements)
    }

    next(): Promise<ChunkPipelineResultWithContext<TMerged, COutput, RPrev> | null> {
        return this.inner.next()
    }

    /**
     * Pull one chunk from the previous pipeline, fan OK elements out into the
     * subpipeline, and emit everything that is already settled (non-OK
     * passthroughs and zero-fan-out completions) without waiting on the sub.
     */
    private async pullAndFanOut(): Promise<PullOutcome<TMerged, COutput, RPrev>> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return { kind: 'drained' }
        }

        const settled: PipelineResultWithContext<TMerged, COutput, RPrev>[] = []
        const subElements: OkResultWithContext<TSub, COutput>[] = []

        for (const element of previousResults) {
            if (!isOkResult(element.result)) {
                settled.push({ result: element.result, context: element.context })
                continue
            }

            const subs = this.fanOutFn(element.result.value)
            if (subs.length === 0) {
                settled.push(this.completeParent(element.result.value, element.context, []))
                continue
            }

            const parent: PendingParent<TElement, TSubOut, COutput> = {
                original: element.result.value,
                // Own copies of the mutable arrays: sub completions push into them.
                context: {
                    ...element.context,
                    sideEffects: [...element.context.sideEffects],
                    warnings: [...element.context.warnings],
                },
                outstanding: subs.length,
                collected: [],
            }
            this.pendingParents.add(parent)
            for (const sub of subs) {
                const subContext: SubContext<TElement, TSubOut, COutput> = {
                    ...element.context,
                    sideEffects: [],
                    warnings: [],
                    [FAN_OUT_PARENT]: parent,
                }
                subElements.push({ result: ok(sub), context: subContext })
            }
        }

        if (subElements.length > 0) {
            this.subPipeline.feed(subElements)
        }

        if (settled.length > 0) {
            return { kind: 'emit', chunk: settled }
        }

        // A non-null empty chunk surfaces as [] (a valid empty chunk, distinct
        // from null = end of stream), matching the previous pipeline 1:1.
        if (subElements.length === 0) {
            return { kind: 'emit', chunk: [] }
        }

        return { kind: 'drain' }
    }

    /**
     * Pull the subpipeline, attribute each sub-result to its parent, and emit
     * the parents whose last sub-result just arrived. Propagates the sub's null
     * (the interleaving loop handles re-pull/drained detection) — but a drained
     * sub with parents still pending means sub-results were lost, which the
     * cardinality contract of chunk stages makes impossible; treat it as a bug.
     */
    private async drainAndFanIn(): Promise<ChunkPipelineResultWithContext<TMerged, COutput, RPrev> | null> {
        while (this.readyResults.length === 0) {
            const subResults = await this.subPipeline.next()
            if (subResults === null) {
                if (this.pendingParents.size > 0) {
                    throw new Error(
                        `Fan-out/fan-in (${this.fanOutName}/${this.fanInName}) subpipeline drained with ` +
                            `${this.pendingParents.size} parent(s) still pending — sub-results were lost`
                    )
                }
                return null
            }
            for (const subResult of subResults) {
                this.settleSubResult(subResult)
            }
        }
        const chunk = this.readyResults
        this.readyResults = []
        return chunk
    }

    private settleSubResult(subResult: PipelineResultWithContext<TSubOut, COutput, RSub>): void {
        const subContext = subResult.context as SubContext<TElement, TSubOut, COutput>
        const parent = subContext[FAN_OUT_PARENT]
        if (!parent) {
            throw new Error(
                `Fan-out/fan-in (${this.fanOutName}/${this.fanInName}) received a sub-result without a ` +
                    `parent tag — the subpipeline must preserve context`
            )
        }

        // Sub contexts start with fresh arrays, so this merges exactly what the
        // sub-steps produced — for excluded sub-results too.
        parent.context.sideEffects.push(...subResult.context.sideEffects)
        parent.context.warnings.push(...subResult.context.warnings)

        if (isOkResult(subResult.result)) {
            parent.collected.push(subResult.result.value)
        } else if (!isDropResult(subResult.result)) {
            // DROP is the sanctioned exclusion; DLQ/REDIRECT for a sub-element
            // is almost certainly misuse — sub-elements are not Kafka messages,
            // so there is nothing to dead-letter or redirect. The sub-result is
            // excluded like a drop, but loudly.
            logger.warn('⚠️', 'Fan-out subpipeline produced a non-droppable non-OK result; excluding it', {
                fanOutStep: this.fanOutName,
                fanInStep: this.fanInName,
                resultType: PipelineResultType[subResult.result.type],
                reason: subResult.result.reason,
            })
        }

        parent.outstanding -= 1
        if (parent.outstanding > 0) {
            return
        }

        this.pendingParents.delete(parent)
        this.readyResults.push(this.completeParent(parent.original, parent.context, parent.collected))
    }

    private completeParent(
        original: TElement,
        context: PipelineContext<COutput>,
        collected: TSubOut[]
    ): PipelineResultWithContext<TMerged, COutput, RPrev> {
        return {
            result: ok(this.fanInFn(original, collected)),
            context: { ...context, lastStep: this.fanInName },
        }
    }
}
