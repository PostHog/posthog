import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { match } from 'ts-pattern'

import {
    GitMetadataParser,
    supportedProviders,
} from '@posthog/products-error-tracking/frontend/components/ReleasesPreview/gitMetadataParser'

import api from 'lib/api'

import type { framesCodeSourceLogicType } from './framesCodeSourceLogicType'
import { stackFrameLogic } from './stackFrameLogic'

export interface SourceData {
    url: string
    provider: string
}

export const framesCodeSourceLogic = kea<framesCodeSourceLogicType>([
    path(['components', 'Errors', 'framesCodeSourceLogic']),

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

                if (!parsed || !supportedProviders.includes(parsed.provider)) {
                    return
                }

                const resolveMethod = match(parsed.provider)
                    .with('github', () => api.gitProviderFileLinks.resolveGithub)
                    .with('gitlab', () => api.gitProviderFileLinks.resolveGitlab)
                    .otherwise(() => null)

                if (!resolveMethod) {
                    return
                }

                const result = await resolveMethod(parsed.owner, parsed.repository, codeSample, fileName)

                if (!result.url) {
                    // Nothing to provide here
                    return
                }

                let url = result.url ?? null

                if (url && lineNumber) {
                    url = `${url}#L${lineNumber + 1}`
                }

                batchData[rawId] = {
                    url,
                    provider: parsed.provider,
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
