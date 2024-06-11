import { FeatureExtractionPipeline, FeatureExtractionPipelineOptions } from '@xenova/transformers'

import { defaultConfig } from '../../../config/config'
import { runInstrumentedFunction } from '../../../main/utils'
import { PreIngestionEvent } from '../../../types'
import { status } from '../../../utils/status'
import { EventPipelineRunner } from './runner'

const options: FeatureExtractionPipelineOptions = { pooling: 'mean', normalize: false }

const errorEmbeddingModel = defaultConfig.ERROR_EVENT_EMBEDDING_MODEL

let featureExtractionPipeline: FeatureExtractionPipeline | null

// this downloads the model the first time it is run, so we do this on server start-up
// we only want to spend the cost of loading the model if we are actually using it
export async function initEmbeddingModel(
    anyTeamsAreEmbeddingEvents: boolean
): Promise<FeatureExtractionPipeline | null> {
    try {
        if (!featureExtractionPipeline && anyTeamsAreEmbeddingEvents) {
            // a little magic here to both delay the slow import until the first time it is needed
            // and to make it work due to some ESM/commonjs faff
            status.info('🤖', 'initialising the error embedding model')
            await runInstrumentedFunction({
                func: async () => {
                    const TransformersApi = Function('return import("@xenova/transformers")')()
                    const { pipeline } = await TransformersApi
                    featureExtractionPipeline = await pipeline('feature-extraction', errorEmbeddingModel)
                    status.info('🤖', 'downloaded and initialised error model')
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

    if (event.teamId >= defaultConfig.ERROR_EMBEDDING_MAX_TEAM_ID) {
        return Promise.resolve(event)
    }

    try {
        if (featureExtractionPipeline === null) {
            status.warn('📭', 'skipping embedding - there was no initialized pipeline')
            return Promise.resolve(event)
        }

        // TODO we should embed the stack trace too or separately, so we can compare grouping with and without that
        let roundedEmbedding: number[] | null = null
        await runInstrumentedFunction({
            func: async () => {
                const output = await featureExtractionPipeline?.(
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
        status.error('💣', 'Error embedding exception event', e)
    }
    return Promise.resolve(event)
}
