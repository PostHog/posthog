import { PersonDisplay, TZLabel, urls } from '@posthog/apps-common'
import { LemonCollapse, LemonDivider, LemonTag, Link, SpinnerOverlay } from '@posthog/lemon-ui'
import classNames from 'classnames'
import { useValues } from 'kea'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import React, { useMemo } from 'react'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LLMGeneration, LLMTrace, TracesQueryResponse } from '~/queries/schema'

import { getDataNodeLogicProps, llmObservabilityTraceLogic } from './llmObservabilityTraceLogic'
import {
    formatAsMarkdownJSONBlock,
    formatLLMCost,
    formatLLMLatency,
    formatLLMUsage,
    formatToolCalls,
    isChoicesOutput,
    isRoleBasedMessage,
    isToolCallsArray,
    RoleBasedMessage,
} from './utils'

export const scene: SceneExport = {
    component: LLMObservabilityTraceScene,
    logic: llmObservabilityTraceLogic,
}

export function LLMObservabilityTraceScene(): JSX.Element {
    const { traceId, query, eventId } = useValues(llmObservabilityTraceLogic)

    const {
        response,
        responseLoading,
        responseError,
        // queryCancelled,
        // nextDataLoading,
        // newDataLoading,
        // highlightedRows,
        // backToSourceQuery,
    } = useValues(dataNodeLogic(getDataNodeLogicProps({ traceId, query })))

    const traceResponse = response as TracesQueryResponse | null
    const event = useMemo(() => {
        const trace = traceResponse?.results?.[0]
        if (!trace) {
            return undefined
        }
        return eventId ? trace.events.find((event) => event.id === eventId) : trace.events[0]
    }, [traceResponse, eventId])

    return (
        <>
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
                <div className="relative pb-4 space-y-4 h-[calc(100vh_-_var(--breadcrumbs-height-full)_-_var(--scene-padding)_-_var(--scene-padding-bottom))] flex flex-col">
                    <TraceMetadata trace={traceResponse.results[0]} />
                    <div className="flex flex-1 min-h-0 gap-4">
                        <TraceSidebar trace={traceResponse.results[0]} eventId={eventId} />
                        <EventContent event={event} />
                    </div>
                </div>
            )}
        </>
    )
}

function Chip({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex gap-2 items-center">
            <span className="font-medium">{title}</span>
            <span>{children}</span>
        </div>
    )
}

function UsageChip({ event }: { event: LLMGeneration | LLMTrace }): JSX.Element | null {
    const usage = formatLLMUsage(event)
    return usage ? <Chip title="Usage">{usage}</Chip> : null
}

function CostChip({ cost, title }: { cost: number; title: string }): JSX.Element {
    return <Chip title={title}>{formatLLMCost(cost)}</Chip>
}

function TraceMetadata({ trace }: { trace: LLMTrace }): JSX.Element {
    return (
        <header className="flex gap-8 flex-wrap border border-border rounded p-4 bg-bg-light text-sm">
            {'person' in trace && (
                <Chip title="Person">
                    <PersonDisplay person={trace.person} />
                </Chip>
            )}
            <UsageChip event={trace} />
            {typeof trace.inputCost === 'number' && <CostChip cost={trace.inputCost} title="Input Cost" />}
            {typeof trace.outputCost === 'number' && <CostChip cost={trace.outputCost} title="Output Cost" />}
            {typeof trace.totalCost === 'number' && <CostChip cost={trace.totalCost} title="Total Cost" />}
        </header>
    )
}

function TraceSidebar({ trace, eventId }: { trace: LLMTrace; eventId?: string | null }): JSX.Element {
    return (
        <aside className="border-border w-72 bg-bg-light border rounded h-full overflow-hidden">
            <header className="px-2 pt-2">
                <h2 className="font-medium text-base p-0 m-0">Timeline</h2>
            </header>
            <LemonDivider />
            <ul className="overflow-y-auto h-full">
                {trace.events.map((event, index) => {
                    const usage = formatLLMUsage(event)
                    const eventSelected = eventId ? eventId === event.id : index === 0
                    return (
                        <li key={event.id} className="border-b border-border">
                            <Link
                                to={urls.llmObservabilityTrace(trace.id, event.id)}
                                className={classNames(
                                    'flex flex-col gap-1 p-2 text-xs hover:bg-primary-highlight',
                                    eventSelected && 'bg-primary-highlight'
                                )}
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

function EventContent({ event }: { event?: LLMGeneration | null }): JSX.Element {
    return (
        <div className="flex-1 bg-bg-light border rounded flex flex-col border-border p-4 overflow-y-auto">
            {!event ? (
                <InsightEmptyState heading="Event not found" detail="Check if the event ID is correct." />
            ) : (
                <>
                    <header>
                        <div className="flex-row flex items-center">
                            <h3 className="text-lg font-medium">
                                {event.model} ({event.provider})
                            </h3>
                        </div>
                        <div className="flex flex-row flex-wrap gap-8">
                            <Chip title="Timestamp">
                                <TZLabel time={event.createdAt} />
                            </Chip>
                            <UsageChip event={event} />
                            {typeof event.totalCost === 'number' && (
                                <CostChip cost={event.totalCost} title="Total Cost" />
                            )}
                            <Chip title="Latency">{formatLLMLatency(event.latency)}</Chip>
                        </div>
                    </header>
                    <LemonDivider className="my-8" />
                    <div className="flex flex-col gap-4">
                        <h4 className="text-base font-medium">Input Messages</h4>
                        <LemonCollapse
                            defaultActiveKeys={event.input.map((_, index) => index.toString())}
                            multiple
                            panels={event.input.map((input, index) => ({
                                key: index.toString(),
                                header: isRoleBasedMessage(input) ? input.role : 'Message without a role',
                                content: <InputRenderer input={input} />,
                            }))}
                        />
                    </div>
                    <LemonDivider className="my-8" />
                    <div className="flex flex-col gap-4">
                        <h4 className="text-base font-medium">Output Messages</h4>
                        <OutputRenderer output={event.output} />
                    </div>
                </>
            )}
        </div>
    )
}

const InputRenderer = React.memo(({ input }: { input: any }) => {
    if (!isRoleBasedMessage(input)) {
        return (
            <InsightEmptyState
                heading="Unsupported input type."
                detail="Please check that your input is a valid array of JSON objects containing the role and content string properties."
            />
        )
    }

    return <LemonMarkdown>{input.content}</LemonMarkdown>
})

InputRenderer.displayName = 'InputRenderer'

const CompletionRenderer = React.memo(({ output }: { output: RoleBasedMessage }) => {
    // Temporary fix for the tool calls since the LangChain integration passes the tool calls in additional_kwargs.
    const toolCalls = output.additional_kwargs?.tool_calls || output.tool_calls

    return (
        <LemonCollapse
            multiple
            defaultActiveKeys={['content', 'tool_calls']}
            panels={[
                {
                    key: 'content',
                    header: output.role,
                    content: <LemonMarkdown>{output.content || JSON.stringify(output.content, null, 2)}</LemonMarkdown>,
                },
                {
                    key: 'tool_calls',
                    header: 'Tool Calls',
                    content: isToolCallsArray(toolCalls) ? (
                        <LemonMarkdown>{formatAsMarkdownJSONBlock(formatToolCalls(toolCalls))}</LemonMarkdown>
                    ) : undefined,
                },
                {
                    key: 'raw',
                    header: 'Raw Output',
                    content: isToolCallsArray(toolCalls) ? (
                        <LemonMarkdown>{formatAsMarkdownJSONBlock(JSON.stringify(output, null, 2))}</LemonMarkdown>
                    ) : undefined,
                },
            ].filter((panel) => panel.content)}
        />
    )
})

CompletionRenderer.displayName = 'CompletionRenderer'

const OutputRenderer = React.memo(({ output }: { output: any }) => {
    if (!isChoicesOutput(output) || output.choices.length === 0) {
        return (
            <div className="min-h-64">
                <LemonMarkdown>{output}</LemonMarkdown>
            </div>
        )
    }

    if (output.choices.length === 1) {
        return <CompletionRenderer output={output.choices[0]} />
    }

    return (
        <LemonCollapse
            multiple
            defaultActiveKeys={output.choices.map((_, index) => index.toString())}
            panels={output.choices.map((choice, index) => ({
                key: index.toString(),
                header: `Completion Choice ${index + 1}`,
                content: <CompletionRenderer output={choice} />,
            }))}
        />
    )
})

OutputRenderer.displayName = 'OutputRenderer'
