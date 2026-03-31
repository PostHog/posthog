import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CSSTransition } from 'react-transition-group'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import MaxTool from 'scenes/max/MaxTool'
import { castAssistantQuery } from 'scenes/max/utils'
import { QUERY_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantPathsQuery,
    AssistantRetentionQuery,
    AssistantStickinessQuery,
    AssistantTrendsQuery,
} from '~/queries/schema/schema-assistant-queries'
import {
    DataVisualizationNode,
    InsightQueryNode,
    InsightVizNode,
    NodeKind,
    QuerySchema,
} from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode } from '~/queries/utils'

import { SessionAnalysisWarning } from './SessionAnalysisWarning'
import { SuggestionBanner } from './SuggestionBanner'

export interface EditorFiltersShellProps {
    query: InsightQueryNode
    showing: boolean
    embedded: boolean
    children: React.ReactNode
}

export function EditorFiltersShell({ query, showing, embedded, children }: EditorFiltersShellProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, shouldShowSessionAnalysisWarning } = useValues(insightVizDataLogic(insightProps))
    const { setQuery } = useActions(insightVizDataLogic(insightProps))
    const { handleInsightSuggested, onRejectSuggestedInsight } = useActions(insightLogic(insightProps))
    const { previousQuery, suggestedQuery } = useValues(insightLogic(insightProps))

    // MaxTool should not be active when insights are embedded (e.g., in notebooks)
    const maxToolActive = !embedded

    const QueryTypeIcon = QUERY_TYPES_METADATA[query.kind].icon

    return (
        <CSSTransition in={showing} timeout={250} classNames="anim-" mountOnEnter unmountOnExit>
            <div className="EditorFiltersWrapper">
                {shouldShowSessionAnalysisWarning ? <SessionAnalysisWarning /> : null}

                <div>
                    <MaxTool
                        identifier="create_insight"
                        context={{
                            current_query: querySource,
                        }}
                        contextDescription={{
                            text: 'Current query',
                            icon: <QueryTypeIcon />,
                        }}
                        callback={(
                            toolOutput:
                                | AssistantTrendsQuery
                                | AssistantFunnelsQuery
                                | AssistantRetentionQuery
                                | AssistantStickinessQuery
                                | AssistantPathsQuery
                                | AssistantHogQLQuery
                        ) => {
                            const source = castAssistantQuery(toolOutput)
                            if (!source) {
                                return
                            }

                            let node: QuerySchema
                            if (isHogQLQuery(source)) {
                                node = {
                                    kind: NodeKind.DataVisualizationNode,
                                    source,
                                } satisfies DataVisualizationNode
                            } else if (isInsightQueryNode(source)) {
                                node = { kind: NodeKind.InsightVizNode, source } satisfies InsightVizNode
                            } else {
                                node = source
                            }

                            handleInsightSuggested(node)
                            setQuery(node)
                        }}
                        initialMaxPrompt="Show me users who "
                        className="EditorFiltersWrapper__max-tool"
                        active={maxToolActive}
                    >
                        <div
                            className={clsx('@container/editor flex flex-row flex-wrap gap-8 bg-surface-primary', {
                                'p-4 rounded border': !embedded,
                            })}
                        >
                            {children}
                        </div>
                    </MaxTool>

                    {previousQuery && (
                        <SuggestionBanner
                            previousQuery={previousQuery}
                            suggestedQuery={suggestedQuery}
                            onReject={onRejectSuggestedInsight}
                        />
                    )}
                </div>
            </div>
        </CSSTransition>
    )
}
