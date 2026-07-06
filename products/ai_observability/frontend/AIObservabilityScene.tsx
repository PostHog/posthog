import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import React from 'react'

import { LemonButton, LemonTab, LemonTabs, Link, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { objectsEqual } from 'lib/utils/objects'
import { EventDetails } from 'scenes/activity/explore/EventDetails'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { ProductKey } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'
import { AccessControlLevel, AccessControlResourceType, DashboardPlacement, EventType } from '~/types'

import { aiObservabilityColumnRenderers } from './aiObservabilityColumnRenderers'
import { AIObservabilityErrors } from './AIObservabilityErrors'
import { AIObservabilityReloadAction } from './AIObservabilityReloadAction'
import { AIObservabilitySessionsPlaylist } from './AIObservabilitySessionsPlaylist'
import { AIObservabilitySetupPrompt } from './AIObservabilitySetupPrompt'
import {
    buildApplyUrlStatePayload,
    AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID,
    aiObservabilitySharedLogic,
} from './aiObservabilitySharedLogic'
import { AIObservabilityTools } from './AIObservabilityTools'
import { AIObservabilityTraces } from './AIObservabilityTracesScene'
import { AIObservabilityUsers } from './AIObservabilityUsers'
import { DOCS_URLS } from './constants'
import { useSortableColumns } from './hooks/useSortableColumns'
import { llmPersonsLazyLoaderLogic } from './llmPersonsLazyLoaderLogic'
import { GENERATION_SENTIMENT_SELECT } from './sentimentResults'
import { aiObservabilityDashboardLogic } from './tabs/aiObservabilityDashboardLogic'
import { aiObservabilityErrorsLogic } from './tabs/aiObservabilityErrorsLogic'
import { getDefaultGenerationsColumns, aiObservabilityGenerationsLogic } from './tabs/aiObservabilityGenerationsLogic'
import { AIObservabilitySentiment } from './tabs/AIObservabilitySentiment'
import { aiObservabilitySentimentLogic } from './tabs/aiObservabilitySentimentLogic'
import { aiObservabilitySessionsViewLogic } from './tabs/aiObservabilitySessionsViewLogic'
import { aiObservabilityToolsLogic } from './tabs/aiObservabilityToolsLogic'
import { aiObservabilityTracesTabLogic } from './tabs/aiObservabilityTracesTabLogic'
import { aiObservabilityUsersLogic } from './tabs/aiObservabilityUsersLogic'
import { AIObservabilityHumanReviews } from './traceReviews/AIObservabilityHumanReviews'
import { getTraceTimestamp, sanitizeTraceUrlSearchParams, truncateValue } from './utils'

export const scene: SceneExport = {
    component: AIObservabilityScene,
    logic: aiObservabilitySharedLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
}

const Filters = ({ hidePropertyFilters = false }: { hidePropertyFilters?: boolean }): JSX.Element => {
    const { dashboardDateFilter, dateFilter, shouldFilterTestAccounts, propertyFilters, activeTab } =
        useValues(aiObservabilitySharedLogic)
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(aiObservabilitySharedLogic)
    const { generationsQuery } = useValues(aiObservabilityGenerationsLogic)
    const { selectedDashboardId } = useValues(aiObservabilityDashboardLogic)

    const dateFrom = activeTab === 'dashboard' ? dashboardDateFilter.dateFrom : dateFilter.dateFrom
    const dateTo = activeTab === 'dashboard' ? dashboardDateFilter.dateTo : dateFilter.dateTo

    return (
        <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 -mt-4 mb-4 border-b">
            <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            {!hidePropertyFilters && (
                <>
                    <PropertyFilters
                        propertyFilters={propertyFilters}
                        taxonomicGroupTypes={generationsQuery.showPropertyFilter as TaxonomicFilterGroupType[]}
                        onChange={setPropertyFilters}
                        pageKey="llm-analytics"
                    />
                    <div className="flex-1" />
                    <TestAccountFilterSwitch
                        checked={shouldFilterTestAccounts}
                        onChange={setShouldFilterTestAccounts}
                    />
                </>
            )}
            {hidePropertyFilters && <div className="flex-1" />}
            {activeTab === 'dashboard' && selectedDashboardId && (
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton type="secondary" size="small" to={urls.dashboard(selectedDashboardId)}>
                        Edit dashboard
                    </LemonButton>
                </AccessControlAction>
            )}
            {activeTab !== 'sentiment' && <AIObservabilityReloadAction />}
        </div>
    )
}

function AIObservabilityDashboard(): JSX.Element {
    const { dashboardDateFilter, propertyFilters } = useValues(aiObservabilitySharedLogic)
    const { selectedDashboardId, availableDashboardsLoading } = useValues(aiObservabilityDashboardLogic)

    const dashboardLogicInstance = React.useMemo(
        () =>
            selectedDashboardId
                ? dashboardLogic({ id: selectedDashboardId, placement: DashboardPlacement.Builtin })
                : null,
        [selectedDashboardId]
    )

    const fallbackLogicInstance = React.useMemo(
        () => dashboardLogic({ id: 0, placement: DashboardPlacement.Builtin }),
        []
    )
    const { externalFilters } = useValues(dashboardLogicInstance || fallbackLogicInstance)
    const dashboardActions = useActions(dashboardLogicInstance || fallbackLogicInstance)
    const setExternalFilters =
        dashboardLogicInstance && dashboardActions?.setExternalFilters ? dashboardActions.setExternalFilters : undefined
    useAttachedLogic(dashboardLogicInstance || fallbackLogicInstance, aiObservabilitySharedLogic)

    const nextExternalFilters = React.useMemo(
        () => ({
            date_from: dashboardDateFilter.dateFrom,
            date_to: dashboardDateFilter.dateTo,
            properties: propertyFilters.length > 0 ? propertyFilters : null,
        }),
        [dashboardDateFilter.dateFrom, dashboardDateFilter.dateTo, propertyFilters]
    )

    const currentExternalFilters = React.useMemo(
        () => ({
            date_from: externalFilters?.date_from ?? null,
            date_to: externalFilters?.date_to ?? null,
            properties: externalFilters?.properties ?? null,
        }),
        [externalFilters?.date_from, externalFilters?.date_to, externalFilters?.properties]
    )

    // Set filters using useLayoutEffect to ensure they're set before Dashboard's afterMount event fires
    React.useLayoutEffect(() => {
        if (selectedDashboardId && setExternalFilters && !objectsEqual(currentExternalFilters, nextExternalFilters)) {
            setExternalFilters(nextExternalFilters)
        }
    }, [currentExternalFilters, nextExternalFilters, selectedDashboardId, setExternalFilters])

    return (
        <AIObservabilitySetupPrompt>
            <div className="@container/dashboard" data-attr="llm-analytics-costs">
                <Filters />

                {availableDashboardsLoading || !selectedDashboardId ? (
                    <div className="text-center p-8">
                        <Spinner captureTime />
                    </div>
                ) : (
                    <Dashboard id={selectedDashboardId.toString()} placement={DashboardPlacement.Builtin} />
                )}
            </div>
        </AIObservabilitySetupPrompt>
    )
}

function AIObservabilityGenerations(): JSX.Element {
    const { applyUrlState } = useActions(aiObservabilitySharedLogic)
    const { dateFilter, propertyFilters: currentPropertyFilters } = useValues(aiObservabilitySharedLogic)
    const { searchParams } = useValues(router)
    const { setGenerationsColumns, toggleGenerationExpanded, setGenerationsSort } = useActions(
        aiObservabilityGenerationsLogic
    )
    const { generationsQuery, expandedGenerationIds, loadedTraces, generationsSort } = useValues(
        aiObservabilityGenerationsLogic
    )

    const { renderSortableColumnTitle } = useSortableColumns(generationsSort, setGenerationsSort)

    // Helper to safely extract uuid and traceId from a result row based on current column configuration
    const getRowIds = (result: unknown): { uuid: string; traceId: string; traceTimestamp?: string } | null => {
        if (!Array.isArray(result) || !isEventsQuery(generationsQuery.source)) {
            return null
        }

        const columns = generationsQuery.source.select || getDefaultGenerationsColumns()

        const uuidIndex = columns.findIndex((col) => col === 'uuid')
        const traceIdIndex = columns.findIndex((col) => col === 'properties.$ai_trace_id')
        const timestampIndex = columns.findIndex((col) => col === 'timestamp')

        if (uuidIndex < 0 || traceIdIndex < 0) {
            return null
        }

        const uuid = result[uuidIndex]
        const traceId = result[traceIdIndex]
        const timestampValue = timestampIndex >= 0 ? result[timestampIndex] : null

        if (typeof uuid === 'string' && typeof traceId === 'string') {
            const parsedTimestamp =
                timestampValue != null && dayjs(String(timestampValue)).isValid()
                    ? getTraceTimestamp(String(timestampValue))
                    : undefined
            return { uuid, traceId, traceTimestamp: parsedTimestamp }
        }

        return null
    }

    return (
        <DataTable
            attachTo={aiObservabilitySharedLogic}
            query={{
                ...generationsQuery,
                showSavedFilters: true,
                defaultColumns: getDefaultGenerationsColumns(),
            }}
            setQuery={(query) => {
                if (!isEventsQuery(query.source)) {
                    throw new Error('Invalid query')
                }
                applyUrlState(
                    buildApplyUrlStatePayload({
                        dateFrom: query.source.after || null,
                        dateTo: query.source.before || null,
                        shouldFilterTestAccounts: query.source.filterTestAccounts || false,
                        propertyFilters: query.source.properties || [],
                        currentDateFilter: dateFilter,
                        currentPropertyFilters,
                    })
                )

                if (query.source.select) {
                    setGenerationsColumns(query.source.select)
                }
            }}
            context={{
                emptyStateHeading: 'There were no generations in this period',
                emptyStateDetail: 'Try changing the date range or filters.',
                columns: {
                    uuid: {
                        title: 'ID',
                        render: ({ record, value }) => {
                            if (!value || typeof value !== 'string') {
                                return null
                            }

                            const ids = getRowIds(record)
                            const visualValue = truncateValue(value)
                            const nonTraceSearchParams = sanitizeTraceUrlSearchParams(searchParams, {
                                removeSearch: true,
                            })

                            return !ids ? (
                                <strong>{visualValue}</strong>
                            ) : (
                                <strong>
                                    <Tooltip title={value}>
                                        <Link
                                            to={
                                                combineUrl(urls.aiObservabilityTrace(ids.traceId), {
                                                    ...nonTraceSearchParams,
                                                    event: value,
                                                    timestamp: ids.traceTimestamp,
                                                    back_to: 'generations',
                                                }).url
                                            }
                                            data-attr="generation-id-link"
                                        >
                                            {visualValue}
                                        </Link>
                                    </Tooltip>
                                </strong>
                            )
                        },
                    },
                    'properties.$ai_input[-1]': {
                        ...aiObservabilityColumnRenderers['properties.$ai_input[-1]'],
                        renderTitle: () => (
                            <Tooltip title="The last message in the input array sent to the LLM for this generation.">
                                <span>Input</span>
                            </Tooltip>
                        ),
                    },
                    'properties.$ai_output_choices': {
                        ...aiObservabilityColumnRenderers['properties.$ai_output_choices'],
                        renderTitle: () => (
                            <Tooltip title="The LLM's response for this generation.">
                                <span>Output</span>
                            </Tooltip>
                        ),
                    },
                    person: aiObservabilityColumnRenderers.person,
                    [GENERATION_SENTIMENT_SELECT]: aiObservabilityColumnRenderers[GENERATION_SENTIMENT_SELECT],
                    'properties.$ai_tools_called': aiObservabilityColumnRenderers['properties.$ai_tools_called'],
                    "f'{properties.$ai_model}' -- Model": {
                        renderTitle: () => renderSortableColumnTitle('properties.$ai_model', 'Model'),
                    },
                    "f'{round(toFloat(properties.$ai_latency), 2)} s' -- Latency": {
                        renderTitle: () => renderSortableColumnTitle('properties.$ai_latency', 'Latency'),
                    },
                    "f'${round(toFloat(properties.$ai_total_cost_usd), 6)}' -- Cost": {
                        renderTitle: () => (
                            <Tooltip title="Cost of this generation">
                                {renderSortableColumnTitle('properties.$ai_total_cost_usd', 'Cost')}
                            </Tooltip>
                        ),
                    },
                    timestamp: {
                        renderTitle: () => renderSortableColumnTitle('timestamp', 'Time'),
                    },
                },
                expandable: {
                    expandedRowRender: function renderExpandedGeneration({ result }: DataTableRow) {
                        const ids = getRowIds(result)

                        if (!ids) {
                            return (
                                <div className="p-4 text-danger">
                                    Cannot expand: required columns (uuid, properties.$ai_trace_id) are missing. Please
                                    reset your column configuration.
                                </div>
                            )
                        }

                        const trace = loadedTraces[ids.traceId]
                        const event = trace?.events.find((e) => e.id === ids.uuid)

                        if (!trace) {
                            return (
                                <div className="p-4">
                                    <Spinner />
                                </div>
                            )
                        }

                        if (!event) {
                            return <div className="p-4">Event not found in trace</div>
                        }

                        // Convert LLMTraceEvent to EventType format for EventDetails
                        const eventForDetails: EventType = {
                            id: event.id,
                            uuid: event.id,
                            distinct_id: '',
                            properties: event.properties,
                            event: event.event,
                            timestamp: event.createdAt,
                            elements: [],
                        }

                        return (
                            <div className="pt-2 px-4 pb-4">
                                <EventDetails event={eventForDetails} />
                            </div>
                        )
                    },
                    rowExpandable: ({ result }: DataTableRow) => !!getRowIds(result),
                    isRowExpanded: ({ result }: DataTableRow) => {
                        const ids = getRowIds(result)
                        return !!ids && expandedGenerationIds.has(ids.uuid)
                    },
                    onRowExpand: ({ result }: DataTableRow) => {
                        const ids = getRowIds(result)
                        if (ids) {
                            toggleGenerationExpanded(ids.uuid, ids.traceId)
                        }
                    },
                    onRowCollapse: ({ result }: DataTableRow) => {
                        const ids = getRowIds(result)
                        if (ids) {
                            toggleGenerationExpanded(ids.uuid, ids.traceId)
                        }
                    },
                    noIndent: true,
                },
            }}
            uniqueKey="llm-analytics-generations"
        />
    )
}

const TAB_DESCRIPTIONS: Record<string, string> = {
    dashboard: 'Overview of your AI usage, costs, and performance metrics.',
    traces: 'Explore end-to-end traces of your LLM interactions.',
    reviews: 'Browse reviews, organize queues, and manage the scoring setup.',
    generations: 'View individual AI generations and their details.',
    users: 'Understand how users are interacting with your AI features.',
    errors: 'Monitor and debug errors in your AI pipeline.',
    tools: 'See which tools your LLMs are calling and how often.',
    sentiment: 'Scan user messages by sentiment to spot frustration or satisfaction.',
    sessions: 'Analyze user sessions containing AI interactions.',
}

export function AIObservabilityScene(): JSX.Element {
    const sharedLogic = aiObservabilitySharedLogic()
    const dataCollectionLogic = dataNodeCollectionLogic({ key: AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID })
    useAttachedLogic(dataCollectionLogic, sharedLogic)

    return (
        <BindLogic logic={aiObservabilitySharedLogic} props={{}}>
            <BindLogic logic={llmPersonsLazyLoaderLogic} props={{}}>
                <BindLogic logic={dataNodeCollectionLogic} props={{ key: AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID }}>
                    <BindLogic logic={aiObservabilityDashboardLogic} props={{}}>
                        <BindLogic logic={aiObservabilityGenerationsLogic} props={{}}>
                            <BindLogic logic={aiObservabilityTracesTabLogic} props={{}}>
                                <BindLogic logic={aiObservabilityErrorsLogic} props={{}}>
                                    <BindLogic logic={aiObservabilityUsersLogic} props={{}}>
                                        <BindLogic logic={aiObservabilitySessionsViewLogic} props={{}}>
                                            <BindLogic logic={aiObservabilityToolsLogic} props={{}}>
                                                <BindLogic logic={aiObservabilitySentimentLogic} props={{}}>
                                                    <AIObservabilitySceneContent />
                                                </BindLogic>
                                            </BindLogic>
                                        </BindLogic>
                                    </BindLogic>
                                </BindLogic>
                            </BindLogic>
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function AIObservabilitySceneContent(): JSX.Element {
    const { activeTab } = useValues(aiObservabilitySharedLogic)
    const { searchParams } = useValues(router)

    const { push } = useActions(router)

    // Tab switching shortcuts
    useShortcut({
        name: 'AIObservabilityTab1',
        keybind: [keyBinds.tab1],
        intent: 'Go to Dashboard',
        interaction: 'function',
        callback: () => push(combineUrl(urls.aiObservabilityDashboard(), searchParams).url),
        scope: Scene.AIObservability,
    })
    useShortcut({
        name: 'AIObservabilityTab2',
        keybind: [keyBinds.tab2],
        intent: 'Go to Traces',
        interaction: 'function',
        callback: () => push(combineUrl(urls.aiObservabilityTraces(), searchParams).url),
        scope: Scene.AIObservability,
    })
    useShortcut({
        name: 'AIObservabilityTab3',
        keybind: [keyBinds.tab3],
        intent: 'Go to Generations',
        interaction: 'function',
        callback: () => push(combineUrl(urls.aiObservabilityGenerations(), searchParams).url),
        scope: Scene.AIObservability,
    })
    useShortcut({
        name: 'AIObservabilityTab4',
        keybind: [keyBinds.tab4],
        intent: 'Go to Users',
        interaction: 'function',
        callback: () => push(combineUrl(urls.aiObservabilityUsers(), searchParams).url),
        scope: Scene.AIObservability,
    })
    useShortcut({
        name: 'AIObservabilityTab5',
        keybind: [keyBinds.tab5],
        intent: 'Go to Errors',
        interaction: 'function',
        callback: () => push(combineUrl(urls.aiObservabilityErrors(), searchParams).url),
        scope: Scene.AIObservability,
    })

    const tabs: LemonTab<string>[] = [
        {
            key: 'dashboard',
            label: 'Dashboard',
            content: <AIObservabilityDashboard />,
            link: combineUrl(urls.aiObservabilityDashboard(), searchParams).url,
            'data-attr': 'dashboard-tab',
        },
        {
            key: 'traces',
            label: 'Traces',
            content: (
                <AIObservabilitySetupPrompt thing="trace">
                    <AIObservabilityTraces />
                </AIObservabilitySetupPrompt>
            ),
            link: combineUrl(urls.aiObservabilityTraces(), searchParams).url,
            'data-attr': 'traces-tab',
        },
        {
            key: 'generations',
            label: 'Generations',
            content: (
                <AIObservabilitySetupPrompt>
                    <AIObservabilityGenerations />
                </AIObservabilitySetupPrompt>
            ),
            link: combineUrl(urls.aiObservabilityGenerations(), searchParams).url,
            'data-attr': 'generations-tab',
        },
        {
            key: 'users',
            label: 'Users',
            content: (
                <AIObservabilitySetupPrompt>
                    <AIObservabilityUsers />
                </AIObservabilitySetupPrompt>
            ),
            link: combineUrl(urls.aiObservabilityUsers(), searchParams).url,
            'data-attr': 'users-tab',
        },
    ]

    tabs.push({
        key: 'errors',
        label: 'Errors',
        content: (
            <AIObservabilitySetupPrompt>
                <AIObservabilityErrors />
            </AIObservabilitySetupPrompt>
        ),
        link: combineUrl(urls.aiObservabilityErrors(), searchParams).url,
        'data-attr': 'errors-tab',
    })

    tabs.push({
        key: 'tools',
        label: 'Tools',
        content: (
            <AIObservabilitySetupPrompt>
                <AIObservabilityTools />
            </AIObservabilitySetupPrompt>
        ),
        link: combineUrl(urls.aiObservabilityTools(), searchParams).url,
        'data-attr': 'tools-tab',
    })

    tabs.push({
        key: 'sentiment',
        label: 'Sentiment',
        content: (
            <AIObservabilitySetupPrompt>
                <Filters />
                <AIObservabilitySentiment />
            </AIObservabilitySetupPrompt>
        ),
        link: combineUrl(urls.aiObservabilitySentiment(), searchParams).url,
        'data-attr': 'llma-sentiment-tab',
    })

    tabs.push({
        key: 'sessions',
        label: 'Sessions',
        content: (
            <AIObservabilitySetupPrompt>
                <Filters />
                <AIObservabilitySessionsPlaylist />
            </AIObservabilitySetupPrompt>
        ),
        link: combineUrl(urls.aiObservabilitySessions(), searchParams).url,
        'data-attr': 'sessions-tab',
    })

    tabs.push({
        key: 'reviews',
        label: 'Reviews',
        content: (
            <AIObservabilitySetupPrompt thing="trace">
                <AIObservabilityHumanReviews />
            </AIObservabilitySetupPrompt>
        ),
        link: combineUrl(urls.aiObservabilityReviews(), searchParams).url,
        'data-attr': 'llma-reviews-tab',
    })

    // Sessions is a primary view — surface it right after Generations, not last.
    const sessionsIdx = tabs.findIndex((t) => t.key === 'sessions')
    if (sessionsIdx > -1) {
        const [sessionsTab] = tabs.splice(sessionsIdx, 1)
        tabs.splice(tabs.findIndex((t) => t.key === 'generations') + 1, 0, sessionsTab)
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.AIObservability].name}
                description={TAB_DESCRIPTIONS[activeTab] || sceneConfigurations[Scene.AIObservability].description}
                resourceType={{
                    type: sceneConfigurations[Scene.AIObservability].iconType || 'default_icon_type',
                }}
                actions={
                    <>
                        <LemonButton
                            to={DOCS_URLS[activeTab] || DOCS_URLS.installation}
                            type="secondary"
                            targetBlank
                            size="small"
                        >
                            Documentation
                        </LemonButton>
                    </>
                }
            />

            <LemonTabs activeKey={activeTab} data-attr="llm-analytics-tabs" tabs={tabs} sceneInset />
        </SceneContent>
    )
}
