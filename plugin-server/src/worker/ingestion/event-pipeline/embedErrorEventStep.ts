import { FeatureExtractionPipeline, FeatureExtractionPipelineOptions } from '@xenova/transformers'

import { defaultConfig } from '../../../config/config'
import { runInstrumentedFunction } from '../../../main/utils'
import { PreIngestionEvent } from '../../../types'
import { status } from '../../../utils/status'
import { EventPipelineRunner } from './runner'

const errorEmbeddingEnabledTeams = (defaultConfig.ENABLE_ERROR_EMBEDDING_TEAM_IDS || '')
    .split(',')
    .map((id) => parseInt(id, 10))

let featureExtractionPipeline: FeatureExtractionPipeline | null

// this downloads the model the first time it is run, so eventually we'll do this on server start-up
// for now we only want to spend the cost of loading the model if we are actually using it
export async function initEmbeddingModel(): Promise<FeatureExtractionPipeline | null> {
    try {
        // if no teams are embedding events, we don't need to load the model
        // this lets us release this and opt in to timing it in production
        const anyTeamsAreEmbeddingEvents = errorEmbeddingEnabledTeams.length > 0

        if (!featureExtractionPipeline && anyTeamsAreEmbeddingEvents) {
            // a little magic here to both delay the slow import until the first time it is needed
            // and to make it work due to some ESM/commonjs faff
            await runInstrumentedFunction({
                func: async () => {
                    const TransformersApi = Function('return import("@xenova/transformers")')()
                    const { pipeline } = await TransformersApi
                    featureExtractionPipeline = await pipeline('feature-extraction', 'Xenova/gte-small')
                },
                statsKey: 'initErrorEventEmbeddingModel',
            })
        }
    } catch (e) {
        status.error('??', 'Error initializing error event embedding model', e)
    }
    return Promise.resolve(featureExtractionPipeline)
}

export async function embedErrorEvent(
    _runner: EventPipelineRunner,
    event: PreIngestionEvent,
    precision = 7
): Promise<PreIngestionEvent> {
    if (event.event !== '$exception') {
        return Promise.resolve(event)
    }

    if (errorEmbeddingEnabledTeams.length === 0 || !errorEmbeddingEnabledTeams.includes(event.teamId)) {
        return Promise.resolve(event)
    }

    try {
        // TODO (can we|do we need to) cache the `currentPipeline`
        const options: FeatureExtractionPipelineOptions = { pooling: 'mean', normalize: false }
        let currentPipeline: FeatureExtractionPipeline | null = null
        await runInstrumentedFunction({
            func: async () => {
                currentPipeline = await initEmbeddingModel()
            },
            statsKey: 'createErrorEmbedPipeline',
        })

        if (currentPipeline === null) {
            return Promise.resolve(event)
        }

        // TODO we should embed the stack trace too or separately, so we can compare grouping with and without that
        let roundedEmbedding: number[] | null = null
        await runInstrumentedFunction({
            func: async () => {
                const output = await currentPipeline?.(
                    `${event.properties['$exception_type']}-${event.properties['$exception_message']}`,
                    options
                )

                roundedEmbedding = output
                    ? Array.from(output.data as number[]).map((value: number) => parseFloat(value.toFixed(precision)))
                    : null
            },
            statsKey: 'generateErrorEventEmbedding',
        })
        if (roundedEmbedding) {
            event.properties['$embedding'] = roundedEmbedding
        }
    } catch (e) {
        status.error('💣', 'Error embedding error event', e)
    }
    return Promise.resolve(event)
}
