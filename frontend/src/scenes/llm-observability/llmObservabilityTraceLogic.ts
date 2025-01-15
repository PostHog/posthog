import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TracesQueryResponse } from '~/queries/schema'
import { Breadcrumb } from '~/types'

import { llmObservabilityLogic } from './llmObservabilityLogic'
import type { llmObservabilityTraceLogicType } from './llmObservabilityTraceLogicType'

export const llmObservabilityTraceLogic = kea<llmObservabilityTraceLogicType>([
    path(['scenes', 'llm-observability', 'llmObservabilityTraceLogic']),

    connect(() => ({
        values: [
            llmObservabilityLogic,
            ['tracesQuery'],
            dataNodeLogic({ key: 'InsightViz.new-AdHoc.DataNode.llm-observability-traces' } as DataNodeLogicProps),
            ['response as cachedTracesResults'],
        ],
    })),

    actions({
        setTraceId: (traceId: string) => ({ traceId }),
    }),

    reducers({
        traceId: [null as string | null, { setTraceId: (_, { traceId }) => traceId }],
    }),

    selectors({
        query: [
            (s) => [s.tracesQuery, s.traceId],
            (tracesQuery, traceId) => ({
                ...tracesQuery,
                source: {
                    ...tracesQuery.source,
                    traceId,
                },
            }),
        ],
        cachedTrace: [
            (s) => [s.cachedTracesResults, s.traceId],
            (cachedTracesResults, traceId) => {
                const response = cachedTracesResults as TracesQueryResponse
                return response.results.find((trace) => trace.id === traceId)
            },
        ],
        breadcrumbs: [
            (s) => [s.traceId],
            (traceId): Breadcrumb[] => {
                return [
                    {
                        key: Scene.LLMObservability,
                        name: 'Traces',
                        path: urls.llmObservability('traces'),
                    },
                    {
                        key: [Scene.LLMObservability, traceId || ''],
                        name: `Trace ${traceId}`,
                    },
                ]
            },
        ],
    }),

    urlToAction(({ actions }) => ({
        [urls.llmObservabilityTrace(':id')]: ({ id }) => {
            actions.setTraceId(id ?? '')
        },
    })),
])
