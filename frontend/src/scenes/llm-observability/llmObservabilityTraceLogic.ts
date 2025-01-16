import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, TracesQuery, TracesQueryResponse } from '~/queries/schema'
import { Breadcrumb, InsightLogicProps } from '~/types'

import { llmObservabilityLogic } from './llmObservabilityLogic'
import type { llmObservabilityTraceLogicType } from './llmObservabilityTraceLogicType'

export interface LLMObservabilityTraceDataNodeLogicParams {
    traceId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
}

export function getDataNodeLogicProps({
    traceId,
    query,
    cachedResults,
}: LLMObservabilityTraceDataNodeLogicParams): DataNodeLogicProps {
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Trace.${traceId}`,
        dataNodeCollectionId: traceId,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: traceId,
        alwaysRefresh: false,
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

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
        setEventId: (eventId: string | null) => ({ eventId }),
    }),

    reducers({
        traceId: ['' as string, { setTraceId: (_, { traceId }) => traceId }],
        eventId: [null as string | null, { setEventId: (_, { eventId }) => eventId }],
    }),

    selectors({
        query: [
            (s) => [s.tracesQuery, s.traceId],
            (tracesQuery, traceId): DataTableNode => ({
                ...tracesQuery,
                source: {
                    ...(tracesQuery.source as TracesQuery),
                    traceId,
                },
            }),
        ],
        cachedTraceResponse: [
            (s) => [s.cachedTracesResults, s.traceId],
            (cachedTracesResults, traceId) => {
                if (!cachedTracesResults) {
                    return null
                }
                const response = cachedTracesResults as TracesQueryResponse

                return {
                    ...response,
                    results: response.results.filter((trace) => trace.id === traceId),
                }
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
        [urls.llmObservabilityTrace(':id')]: ({ id }, { event }) => {
            actions.setTraceId(id ?? '')
            actions.setEventId(event || null)
        },
    })),
])
