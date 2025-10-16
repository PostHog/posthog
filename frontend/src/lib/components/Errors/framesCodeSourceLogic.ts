import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { GitMetadataParser } from '@posthog/products-error-tracking/frontend/components/ExceptionAttributesPreview/ReleasesPreview/gitMetadataParser'

import api from 'lib/api'

import { ErrorPropertiesLogicProps } from './errorPropertiesLogic'
import type { framesCodeSourceLogicType } from './framesCodeSourceLogicType'
import { stackFrameLogic } from './stackFrameLogic'

export const framesCodeSourceLogic = kea<framesCodeSourceLogicType>([
    path(['components', 'Errors', 'framesCodeSourceLogic']),

    props({} as ErrorPropertiesLogicProps),

    connect({
        values: [stackFrameLogic, ['stackFrameRecords']],
    }),

    actions({
        setSourceUrl: (rawId: string, url: string | null) => ({ rawId, url }),
        computeSourceUrls: true,
    }),

    reducers({
        frameSourceUrls: [
            {} as Record<string, string | null>,
            {
                setSourceUrl: (state, { rawId, url }) => ({
                    ...state,
                    [rawId]: url,
                }),
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        computeSourceUrls: async () => {
            const records = values.stackFrameRecords

            const searchPromises = Object.entries(records).map(async ([rawId, record]) => {
                // Skip if already computed or not in-app
                if (values.frameSourceUrls[rawId] !== undefined || !record.contents?.in_app) {
                    return
                }

                const codeSample = record.context?.line.line
                const remoteUrl = record.release?.metadata?.git?.remote_url

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
                    actions.setSourceUrl(rawId, result.found && result.url ? result.url : null)
                }
            })

            await Promise.all(searchPromises)
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
        getSourceUrlForFrame: [
            (s) => [s.frameSourceUrls],
            (frameSourceUrls: Record<string, string | null>) => (rawId: string) => frameSourceUrls[rawId] || null,
        ],
    }),
])
