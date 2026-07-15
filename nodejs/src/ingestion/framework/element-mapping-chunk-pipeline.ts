import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { PipelineResultWithContext } from './pipeline.interface'
import { ok } from './results'

export type ElementMappingFunction<TOutput, COutput, U, R extends string = never> = (
    element: PipelineResultWithContext<TOutput, COutput, R>
) => U

/**
 * A chunk pipeline stage that maps every element — non-OK results included — to a final OK value,
 * reading both the result and its context. Run it after result and side-effect handling: by then a
 * non-OK result's fate is sealed (its DLQ/overflow produce is scheduled, its drop is accounted), so
 * what flows on is just the per-message row downstream readers need — e.g. the source partition and
 * offset to commit. This is also where heavy contexts die: the emitted elements carry an empty
 * domain context, keeping only the framework part (lastStep, side effects, warnings).
 */
export class ElementMappingChunkPipeline<TInput, TOutput, CInput, COutput, U, R extends string = never>
    implements ChunkPipeline<TInput, U, CInput, Record<never, object>, R>
{
    constructor(
        private subPipeline: ChunkPipeline<TInput, TOutput, CInput, COutput, R>,
        private mapFn: ElementMappingFunction<TOutput, COutput, U, R>
    ) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<ChunkPipelineResultWithContext<U, Record<never, object>, R> | null> {
        const results = await this.subPipeline.next()
        if (results === null) {
            return null
        }
        return results.map((element) => ({
            result: ok(this.mapFn(element)),
            context: {
                lastStep: element.context.lastStep,
                sideEffects: element.context.sideEffects,
                warnings: element.context.warnings,
            },
        }))
    }
}
