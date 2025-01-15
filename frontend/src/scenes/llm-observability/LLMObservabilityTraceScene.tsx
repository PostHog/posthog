import { PersonDisplay, urls } from '@posthog/apps-common'
import { LemonDivider, LemonTag, Link, SpinnerOverlay } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useRef } from 'react'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { DataTableNode, LLMTrace, TracesQueryResponse } from '~/queries/schema'
import { InsightLogicProps } from '~/types'

import { llmObservabilityTraceLogic } from './llmObservabilityTraceLogic'
import { formatLLMCost, formatLLMLatency, formatLLMUsage } from './utils'

export const scene: SceneExport = {
    component: LLMObservabilityTraceScene,
    logic: llmObservabilityTraceLogic,
}

export function LLMObservabilityTraceScene(): JSX.Element {
    const { traceId, query } = useValues(llmObservabilityTraceLogic)

    const dataKey = useRef(`TraceScene.${traceId}`).current
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-AdHoc.${dataKey}`,
        dataNodeCollectionId: dataKey,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: dataKey,
    }
    const builtDataNodeLogic = dataNodeLogic(dataNodeLogicProps)

    const {
        response,
        responseLoading,
        responseError,
        // queryCancelled,
        // nextDataLoading,
        // newDataLoading,
        // highlightedRows,
        // backToSourceQuery,
    } = useValues(builtDataNodeLogic)

    const traceResponse = response as TracesQueryResponse | null

    return (
        <div className="flex flex-col p-4 pt-0 flex-1 gap-4">
            {responseLoading ? (
                <SpinnerOverlay />
            ) : responseError ? (
                <InsightErrorState />
            ) : !traceResponse || traceResponse.results.length === 0 ? (
                <InsightEmptyState
                    heading={`The trace with ID ${traceId} has not been found`}
                    detail="Check if the trace ID is correct."
                />
            ) : (
                <>
                    <TraceMetadata trace={traceResponse.results[0]} />
                    <div className="flex flex-1 gap-4">
                        <TraceSidebar trace={traceResponse.results[0]} />
                        <div className="flex-1 bg-bg-light border rounded flex flex-col border-border" />
                    </div>
                </>
            )}
        </div>
    )
}

function TraceMetadata({ trace }: { trace: LLMTrace }): JSX.Element {
    return (
        <header className="flex gap-8 flex-wrap border border-border rounded p-4 bg-bg-light text-sm">
            <div className="flex gap-2">
                <span className="font-medium">Person</span>
                <PersonDisplay person={trace.person} />
            </div>
            <div className="flex gap-2">
                <span className="font-medium">Usage</span>
                <span>{formatLLMUsage(trace)}</span>
            </div>
            <div className="flex gap-2">
                <span className="font-medium">Input Cost</span>
                <span>${trace.inputCost}</span>
            </div>
            <div className="flex gap-2">
                <span className="font-medium">Output Cost</span>
                <span>${trace.outputCost}</span>
            </div>
        </header>
    )
}

function TraceSidebar({ trace }: { trace: LLMTrace }): JSX.Element {
    return (
        <aside className="border-border max-w-80 min-w-72 bg-bg-light border rounded">
            <header className="px-2 pt-2">
                <h2 className="font-medium text-base p-0 m-0">Timeline</h2>
            </header>
            <LemonDivider />
            <ul className="overflow-y-auto h-full">
                {trace.events.map((event) => {
                    const usage = formatLLMUsage(event)
                    return (
                        <li key={event.id} className="border-b border-border">
                            <Link
                                to={urls.llmObservabilityTrace(trace.id, event.id)}
                                className="flex flex-col gap-1 p-2 text-xs hover:bg-primary-highlight"
                            >
                                <div className="flex flex-row flex-wrap items-center">
                                    <LemonTag className="mr-2">Generation</LemonTag> {event.model} ({event.provider})
                                </div>
                                <div className="flex flex-row flex-wrap text-muted items-center gap-2">
                                    <LemonTag type="muted">{formatLLMLatency(event.latency)}</LemonTag>
                                    {usage && <span>{usage}</span>}
                                    {event.totalCost && <span>{formatLLMCost(event.totalCost)}</span>}
                                </div>
                            </Link>
                        </li>
                    )
                })}
            </ul>
        </aside>
    )
}
