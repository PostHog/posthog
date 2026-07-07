import { PluginEvent } from '~/plugin-scaffold'

/**
 * Contract for the hog transformation service, consumed by ingestion.
 *
 * The concrete implementation (`HogTransformerService`) lives in cdp because it depends on the
 * full hog execution machinery (executor, managers, templates, plugins). Ingestion depends only
 * on this interface and receives an instance by injection from the server wiring layer, so
 * ingestion never imports cdp.
 */
export interface HogTransformationResult {
    event: PluginEvent | null
    // Opaque to ingestion (it only reads `.length`); cdp narrows this to its concrete result type.
    invocationResults: unknown[]
}

export interface HogTransformer {
    start(): Promise<void>
    stop(): Promise<void>
    processInvocationResults(): Promise<void>
    transformEventAndProduceMessages(event: PluginEvent): Promise<HogTransformationResult>
    // Refresh cached transformation hog-function states for the given teams (used by the ingestion
    // prefetch step). Encapsulates the hog-function-manager lookup ingestion would otherwise reach into.
    prefetchTransformationStatesForTeams(teamIds: number[]): Promise<void>
}
