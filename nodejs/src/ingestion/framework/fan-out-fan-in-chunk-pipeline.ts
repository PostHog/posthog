import { logger } from '~/common/utils/logger'

import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { InterleavingChunkPipeline, PullOutcome } from './interleaving-chunk-pipeline'
import { PipelineContext, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResultType, dlq, isDlqResult, isDropResult, isOkResult, ok } from './results'

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
 * `concurrentlyPerGroup`) — index-based correlation would not.
 */
export const FAN_OUT_PARENT = Symbol('fanOutParent')

/**
 * Opaque token correlating a sub-element back to its parent. The stage mints
 * one per fanned-out parent; the private brand makes the type nominal, so no
 * structurally-forged object passes for one. Sub steps may see the token on
 * their context but can't do anything with it — a token the stage doesn't
 * recognize fails loudly on fan-in.
 */
export class FanOutParentRef {
    declare private readonly fanOutParentBrand: never
}

/**
 * The context type sub-elements carry: nothing but the correlation tag (plus
 * the base `PipelineContext` fields, with fresh per-sub arrays). Sub-pipelines
 * are context-agnostic — decoupled from the parent pipeline's context type, so
 * context-gated builder surface (`teamAware`, `messageAware`,
 * `handleIngestionWarnings`, `handleResults`) is uncallable inside them. Not
 * deriving sub contexts from the parent's also keeps an inner nested fan-out's
 * subs from carrying an outer stage's tag.
 */
export type FanOutSubContext = { readonly [FAN_OUT_PARENT]: FanOutParentRef }

interface PendingParent<TElement, TSubOut, C> {
    original: TElement
    /** The element's context, owned by the stage; sub completions push side effects/warnings into it in place. */
    context: PipelineContext<C>
    outstanding: number
    /** How many sub-elements were fanned out, for the aggregated DLQ reason. */
    total: number
    collected: TSubOut[]
    /** Sub DLQs seen so far; when non-empty the parent DLQs instead of fanning in. */
    dlqFailures: { reason: string; error: unknown }[]
    /** lastStep of the most recent DLQ sub-result, for error attribution on the parent. */
    dlqLastStep: string | undefined
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
 * 3. When all of a parent's sub-results are in, the parent settles:
 *    - OK contributes its value to `collected`.
 *    - DROP is the sanctioned way for a sub-step to exclude a sub-element:
 *      it contributes nothing, silently — the parent fans in with the
 *      survivors, consistent with a zero-fan-out fanning in with `[]`.
 *    - DLQ fails the whole parent: instead of fanning in, the parent emits a
 *      DLQ aggregating its sub DLQs (count, distinct reasons, and every sub
 *      error via AggregateError) once all of its siblings have drained.
 *      Fanning in anyway could emit an element built for work that never
 *      happened — e.g. a pointer to a blob that was never stored.
 *    - REDIRECT contributes nothing but logs a warning: it is almost
 *      certainly misuse, since sub-elements are not Kafka messages — route
 *      the parent before fanning out instead.
 *    Side effects and warnings from every sub-result (OK or not) still merge
 *    into the parent context.
 *
 * Cardinality is preserved at the parent level: N parents in, N results out.
 * Sub-element cardinality is fully contained inside the stage — and so are
 * the subpipeline's redirect names: a redirect can never escape as the
 * parent's result (and a DLQ carries no redirect names), so the stage emits
 * only the upstream's redirect names (`RPrev`, not `RPrev | RSub`).
 *
 * Ordering: parents emit as their sub-results complete (unordered), the same
 * contract as `concurrentlyPerGroup`. Non-OK parents pass through untouched.
 *
 * Sub-pipelines are context-agnostic: their context type is
 * {@link FanOutSubContext} — nothing but a public, opaque correlation token —
 * so context-gated surface like `teamAware`, `messageAware`,
 * `handleIngestionWarnings`, and `handleResults` is uncallable inside them.
 * Sub warnings and side effects merge into the parent and are handled once by
 * the outer pipeline. If sub-steps need team or message data, the fan-out
 * function should put it in the sub-element value.
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
    private pendingParents = new Map<FanOutParentRef, PendingParent<TElement, TSubOut, COutput>>()
    /** Parents completed by sub-results, drained by onProcessPull before pulling the subpipeline again. */
    private readyResults: PipelineResultWithContext<TMerged, COutput, RPrev>[] = []
    // Bumped in the same synchronous block that registers parents and feeds
    // their subs; lets drainAndFanIn tell a fan-out that raced its pull apart
    // from genuinely lost sub-results (mirrors BatchingPipeline's feedEpoch).
    private fanOutEpoch = 0
    private fanOutName: string
    private fanInName: string

    constructor(
        private previousPipeline: ChunkPipeline<TInput, TElement, CInput, COutput, RPrev>,
        private fanOutFn: FanOutFunction<TElement, TSub>,
        private subPipeline: ChunkPipeline<TSub, TSubOut, FanOutSubContext, FanOutSubContext, RSub>,
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
        const subElements: OkResultWithContext<TSub, FanOutSubContext>[] = []

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

            // Ownership: once pulled, this stage is the element's only holder —
            // upstream stages build a fresh context object (and arrays) per
            // step and retain nothing after emitting the chunk. So the parent
            // keeps the element's context as-is and sub completions push into
            // its arrays in place; the framework's copy-per-step idiom exists
            // to isolate steps from each other, which doesn't apply here.
            const parent: PendingParent<TElement, TSubOut, COutput> = {
                original: element.result.value,
                context: element.context,
                outstanding: subs.length,
                total: subs.length,
                collected: [],
                dlqFailures: [],
                dlqLastStep: undefined,
            }
            const ref = new FanOutParentRef()
            this.pendingParents.set(ref, parent)
            for (const sub of subs) {
                const subContext: PipelineContext<FanOutSubContext> = {
                    sideEffects: [],
                    warnings: [],
                    [FAN_OUT_PARENT]: ref,
                }
                subElements.push({ result: ok(sub), context: subContext })
            }
        }

        if (subElements.length > 0) {
            this.fanOutEpoch++
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
            const epochAtPullStart = this.fanOutEpoch
            const subResults = await this.subPipeline.next()
            if (subResults === null) {
                if (this.pendingParents.size > 0) {
                    // A fan-out can land while this pull is resolving null from
                    // an empty subpipeline (the interleaving loop races process
                    // pulls against source pulls). A changed epoch proves that's
                    // what happened — retry the pull, which now sees the fed
                    // subs. An unchanged epoch means sub-results genuinely
                    // vanished, which the cardinality contract of chunk stages
                    // makes impossible; treat it as a bug.
                    if (this.fanOutEpoch !== epochAtPullStart) {
                        continue
                    }
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

    private settleSubResult(subResult: PipelineResultWithContext<TSubOut, FanOutSubContext, RSub>): void {
        const ref = subResult.context[FAN_OUT_PARENT]
        const parent = this.pendingParents.get(ref)
        if (!parent) {
            // Also catches forged or stale tokens: an unknown ref fails loudly
            // here instead of silently settling against whatever it pointed at.
            throw new Error(
                `Fan-out/fan-in (${this.fanOutName}/${this.fanInName}) received a sub-result without a ` +
                    `known parent tag — the subpipeline must preserve context`
            )
        }

        // Sub contexts start with fresh arrays, so this merges exactly what the
        // sub-steps produced — for excluded sub-results too. The pushes land in
        // the parent's owned context (see pullAndFanOut).
        parent.context.sideEffects.push(...subResult.context.sideEffects)
        parent.context.warnings.push(...subResult.context.warnings)

        if (isOkResult(subResult.result)) {
            parent.collected.push(subResult.result.value)
        } else if (isDlqResult(subResult.result)) {
            // A sub-element that must be dead-lettered fails its whole parent:
            // fanning in regardless could emit an element built for work that
            // never happened. The parent's DLQ is emitted once every sibling
            // has drained.
            parent.dlqFailures.push({ reason: subResult.result.reason, error: subResult.result.error })
            parent.dlqLastStep = subResult.context.lastStep
        } else if (!isDropResult(subResult.result)) {
            // DROP is the sanctioned exclusion; a REDIRECT for a sub-element is
            // almost certainly misuse — sub-elements are not Kafka messages, so
            // there is nothing to redirect. Excluded like a drop, but loudly.
            logger.warn('⚠️', 'Fan-out subpipeline produced a redirect result; excluding it', {
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

        this.pendingParents.delete(ref)
        if (parent.dlqFailures.length > 0) {
            this.readyResults.push(this.failParent(parent))
        } else {
            this.readyResults.push(this.completeParent(parent.original, parent.context, parent.collected))
        }
    }

    /**
     * Emit the parent as a DLQ aggregating its sub DLQs. Every sub-result has
     * drained by now, so the context already carries all sibling side effects
     * and warnings; collected values are discarded.
     */
    private failParent(
        parent: PendingParent<TElement, TSubOut, COutput>
    ): PipelineResultWithContext<TMerged, COutput, RPrev> {
        const reasons = [...new Set(parent.dlqFailures.map((failure) => failure.reason))]
        const reason = `${parent.dlqFailures.length}/${parent.total} fan-out sub-elements dlq'd: ${reasons.join('; ')}`
        parent.context.lastStep = parent.dlqLastStep
        return {
            result: dlq(
                reason,
                new AggregateError(
                    parent.dlqFailures.map((failure) => failure.error),
                    reason
                )
            ),
            context: parent.context,
        }
    }

    private completeParent(
        original: TElement,
        context: PipelineContext<COutput>,
        collected: TSubOut[]
    ): PipelineResultWithContext<TMerged, COutput, RPrev> {
        // Same ownership invariant as in pullAndFanOut: the context is
        // uniquely held by this stage, so set lastStep in place.
        context.lastStep = this.fanInName
        return { result: ok(this.fanInFn(original, collected)), context }
    }
}
