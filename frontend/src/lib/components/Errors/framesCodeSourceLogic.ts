import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { GitMetadataParser } from '@posthog/products-error-tracking/frontend/components/ExceptionAttributesPreview/ReleasesPreview/gitMetadataParser'

import api from 'lib/api'

import { ErrorPropertiesLogicProps } from './errorPropertiesLogic'
import type { framesCodeSourceLogicType } from './framesCodeSourceLogicType'
import { stackFrameLogic } from './stackFrameLogic'

export interface SourceData {
    url: string | null
    provider: string | null
}

export const framesCodeSourceLogic = kea<framesCodeSourceLogicType>([
    path(['components', 'Errors', 'framesCodeSourceLogic']),

    props({} as ErrorPropertiesLogicProps),

    connect({
        values: [stackFrameLogic, ['stackFrameRecords']],
    }),

    actions({
        setSourceData: (data: Record<string, SourceData | null>) => ({ data }),
        computeSourceUrls: true,
    }),

    reducers({
        frameSourceUrls: [
            {} as Record<string, SourceData | null>,
            {
                setSourceData: (state, { data }) => ({
                    ...state,
                    ...data,
                }),
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        computeSourceUrls: async () => {
            const records = values.stackFrameRecords
            const batchData: Record<string, SourceData | null> = {}

            const searchPromises = Object.entries(records).map(async ([rawId, record]) => {
                // Skip if already computed or not in-app
                if (values.frameSourceUrls[rawId] !== undefined || !record.contents?.in_app) {
                    return
                }

                const codeSample = record.context?.line.line
                const remoteUrl = record.release?.metadata?.git?.remote_url
                const lineNumber = record.context?.line.number

                if (!record.contents.source) {
                    return
                }

                const fileName = record.contents.source.split('/').pop()

                if (!codeSample || !remoteUrl || !fileName) {
                    return
                }

                const parsed = GitMetadataParser.parseRemoteUrl(remoteUrl)

                if (parsed?.provider === 'github') {
                    const result = await api.gitProviderFileLinks.resolveGithub(
                        parsed.owner,
                        parsed.repository,
                        codeSample,
                        fileName
                    )
                    let url = result.found && result.url ? `${result.url}` : null

                    if (url && lineNumber) {
                        url = `${url}#L${lineNumber + 1}`
                    }

                    batchData[rawId] = {
                        url,
                        provider: parsed.provider,
                    }
                }
            })

            await Promise.all(searchPromises)

            actions.setSourceData(batchData)
        },
    })),

    subscriptions(({ actions }) => ({
        stackFrameRecords: (stackFrameRecords) => {
            if (Object.keys(stackFrameRecords).length > 0) {
                actions.computeSourceUrls()
            }
        },
    })),

    selectors({
        getSourceDataForFrame: [
            (s) => [s.frameSourceUrls],
            (frameSourceUrls: Record<string, SourceData | null>) => (rawId: string) => frameSourceUrls[rawId] || null,
        ],
    }),
])
