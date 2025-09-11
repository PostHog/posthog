import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconArchive } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTab, LemonTabs, LemonTag, Link } from '@posthog/lemon-ui'

import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'

import { LLMMessageDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { LLMAnalyticsPlaygroundScene } from './LLMAnalyticsPlaygroundScene'
import { LLMAnalyticsReloadAction } from './LLMAnalyticsReloadAction'
import { LLMAnalyticsTraces } from './LLMAnalyticsTracesScene'
import { LLMAnalyticsUsers } from './LLMAnalyticsUsers'
import { LLMAnalyticsDatasetsScene } from './datasets/LLMAnalyticsDatasetsScene'
import { LLM_ANALYTICS_DATA_COLLECTION_NODE_ID, llmAnalyticsLogic } from './llmAnalyticsLogic'
import { CompatMessage } from './types'
import { normalizeMessages, truncateValue } from './utils'

export const scene: SceneExport = {
    component: LLMAnalyticsScene,
}

const Filters = (): JSX.Element => {
    const { dashboardDateFilter, dateFilter, shouldFilterTestAccounts, generationsQuery, propertyFilters, activeTab } =
        useValues(llmAnalyticsLogic)
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmAnalyticsLogic)

    const dateFrom = activeTab === 'dashboard' ? dashboardDateFilter.dateFrom : dateFilter.dateFrom
    const dateTo = activeTab === 'dashboard' ? dashboardDateFilter.dateTo : dateFilter.dateTo

    return (
        <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 -mt-4 mb-4 border-b">
            <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            <PropertyFilters
                propertyFilters={propertyFilters}
                taxonomicGroupTypes={generationsQuery.showPropertyFilter as TaxonomicFilterGroupType[]}
                onChange={setPropertyFilters}
                pageKey="llm-analytics"
            />
            <div className="flex-1" />
            <TestAccountFilterSwitch checked={shouldFilterTestAccounts} onChange={setShouldFilterTestAccounts} />
            <LLMAnalyticsReloadAction />
        </div>
    )
}

const Tiles = (): JSX.Element => {
    const { tiles } = useValues(llmAnalyticsLogic)

    return (
        <div className="mt-2 grid grid-cols-1 @xl/dashboard:grid-cols-2 @4xl/dashboard:grid-cols-6 gap-4">
            {tiles.map(({ title, description, query, context }, i) => (
                <QueryCard
                    key={i}
                    title={title}
                    description={description}
                    query={{ kind: NodeKind.InsightVizNode, source: query } as InsightVizNode}
                    context={context}
                    className={clsx(
                        'h-96',
                        /* Second row is the only one to have 2 tiles in the xl layout */
                        i < 3 || i >= 5 ? '@4xl/dashboard:col-span-2' : '@4xl/dashboard:col-span-3'
                    )}
                />
            ))}
        </div>
    )
}

const IngestionStatusCheck = (): JSX.Element | null => {
    return (
        <LemonBanner type="warning">
            <p>
                <strong>No LLM generation events have been detected!</strong>
            </p>
            <p>
                To use the LLM Analytics product, please{' '}
                <Link to="https://posthog.com/docs/llm-analytics/installation">
                    instrument your LLM calls with the PostHog SDK
                </Link>{' '}
                (otherwise it'll be a little empty!)
            </p>
        </LemonBanner>
    )
}

function LLMAnalyticsDashboard(): JSX.Element {
    return (
        <div className="@container/dashboard">
            <Filters />
            <Tiles />
        </div>
    )
}

function LLMAnalyticsGenerations(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters, setGenerationsQuery, setGenerationsColumns } =
        useActions(llmAnalyticsLogic)
    const { generationsQuery } = useValues(llmAnalyticsLogic)

    return (
        <DataTable
            query={{
                ...generationsQuery,
                showSavedFilters: true,
            }}
            setQuery={(query) => {
                if (!isEventsQuery(query.source)) {
                    throw new Error('Invalid query')
                }
                setDates(query.source.after || null, query.source.before || null)
                setShouldFilterTestAccounts(query.source.filterTestAccounts || false)
                setPropertyFilters(query.source.properties || [])

                if (query.source.select) {
                    setGenerationsColumns(query.source.select)
                }

                setGenerationsQuery(query)
            }}
            context={{
                emptyStateHeading: 'There were no generations in this period',
                emptyStateDetail: 'Try changing the date range or filters.',
                columns: {
                    uuid: {
                        title: 'ID',
                        render: ({ record, value }) => {
                            const traceId = (record as unknown[])[1]
                            if (!value) {
                                return <></>
                            }

                            const visualValue = truncateValue(value)

                            if (!traceId) {
                                return <strong>{visualValue}</strong>
                            }

                            return (
                                <strong>
                                    <Tooltip title={value as string}>
                                        <Link to={`/llm-analytics/traces/${traceId}?event=${value as string}`}>
                                            {visualValue}
                                        </Link>
                                    </Tooltip>
                                </strong>
                            )
                        },
                    },
                    'properties.$ai_input[-1]': {
                        title: 'Input',
                        render: ({ value }) => {
                            let inputNormalized: CompatMessage[] | undefined
                            if (typeof value === 'string') {
                                try {
                                    inputNormalized = normalizeMessages(JSON.parse(value), 'user')
                                } catch (e) {
                                    console.warn('Error parsing properties.$ai_input[-1] as JSON', e)
                                }
                            }
                            if (!inputNormalized?.length) {
                                return <>–</>
                            }
                            return <LLMMessageDisplay message={inputNormalized.at(-1)!} isOutput={false} minimal />
                        },
                    },
                    'properties.$ai_output_choices': {
                        title: 'Output',
                        render: ({ value }) => {
                            let outputNormalized: CompatMessage[] | undefined
                            if (typeof value === 'string') {
                                try {
                                    outputNormalized = normalizeMessages(JSON.parse(value), 'assistant')
                                } catch (e) {
                                    console.warn('Error parsing properties.$ai_output_choices as JSON', e)
                                }
                            }
                            if (!outputNormalized?.length) {
                                return <>–</>
                            }
                            return (
                                <div>
                                    {outputNormalized.map(
                                        (
                                            message,
                                            index // All output choices, if multiple
                                        ) => (
                                            <LLMMessageDisplay key={index} message={message} isOutput={true} minimal />
                                        )
                                    )}
                                </div>
                            )
                        },
                    },
                    'properties.$ai_trace_id': {
                        title: 'Trace ID',
                        render: ({ value }) => {
                            if (!value) {
                                return <></>
                            }

                            const visualValue = truncateValue(value)

                            return (
                                <Tooltip title={value as string}>
                                    <Link to={`/llm-analytics/traces/${value as string}`}>{visualValue}</Link>
                                </Tooltip>
                            )
                        },
                    },
                },
            }}
            uniqueKey="llm-analytics-generations"
        />
    )
}

function LLMAnalyticsNoEvents(): JSX.Element {
    return (
        <div className="w-full flex flex-col items-center justify-center">
            <div className="flex flex-col items-center justify-center max-w-md w-full">
                <IconArchive className="text-5xl mb-2 text-muted-alt" />
                <h2 className="text-xl leading-tight">We haven't detected any LLM generations yet</h2>
                <p className="text-sm text-center text-balance">
                    To use the LLM Analytics product, please{' '}
                    <Link to="https://posthog.com/docs/llm-analytics/installation">
                        instrument your LLM calls with the PostHog SDK
                    </Link>{' '}
                </p>
            </div>
        </div>
    )
}

export function LLMAnalyticsScene(): JSX.Element {
    const { activeTab, hasSentAiGenerationEvent, hasSentAiGenerationEventLoading } = useValues(llmAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { searchParams } = useValues(router)

    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    const tabs: LemonTab<string>[] = [
        {
            key: 'dashboard',
            label: 'Dashboard',
            content: <LLMAnalyticsDashboard />,
            link: combineUrl(urls.llmAnalyticsDashboard(), searchParams).url,
        },
        {
            key: 'traces',
            label: 'Traces',
            content: hasSentAiGenerationEvent ? <LLMAnalyticsTraces /> : <LLMAnalyticsNoEvents />,
            link: combineUrl(urls.llmAnalyticsTraces(), searchParams).url,
        },
        {
            key: 'generations',
            label: 'Generations',
            content: hasSentAiGenerationEvent ? <LLMAnalyticsGenerations /> : <LLMAnalyticsNoEvents />,
            link: combineUrl(urls.llmAnalyticsGenerations(), searchParams).url,
        },
        {
            key: 'users',
            label: 'Users',
            content: hasSentAiGenerationEvent ? <LLMAnalyticsUsers /> : <LLMAnalyticsNoEvents />,
            link: combineUrl(urls.llmAnalyticsUsers(), searchParams).url,
        },
    ]

    if (featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_PLAYGROUND]) {
        tabs.push({
            key: 'playground',
            label: (
                <>
                    Playground{' '}
                    <LemonTag className="ml-1" type="warning">
                        Beta
                    </LemonTag>
                </>
            ),
            content: <LLMAnalyticsPlaygroundScene />,
            link: combineUrl(urls.llmAnalyticsPlayground(), searchParams).url,
        })
    }

    if (featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]) {
        tabs.push({
            key: 'datasets',
            label: (
                <>
                    Datasets{' '}
                    <LemonTag className="ml-1" type="warning">
                        Beta
                    </LemonTag>
                </>
            ),
            content: <LLMAnalyticsDatasetsScene />,
            link: combineUrl(urls.llmAnalyticsDatasets(), searchParams).url,
            'data-attr': 'datasets-tab',
        })
    }

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: LLM_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <PageHeader
                buttons={
                    <div className="flex gap-2">
                        <LemonButton
                            to="https://posthog.com/docs/llm-analytics/installation"
                            type="secondary"
                            targetBlank
                        >
                            Documentation
                        </LemonButton>
                    </div>
                }
            />

            <SceneContent>
                {!hasSentAiGenerationEventLoading && !hasSentAiGenerationEvent && <IngestionStatusCheck />}
                <SceneTitleSection
                    name="LLM Analytics"
                    description="Analyze and understand your LLM usage and performance."
                    resourceType={{
                        type: 'llm_analytics',
                    }}
                />
                <SceneDivider />

                <LemonTabs
                    activeKey={activeTab}
                    data-attr="llm-analytics-tabs"
                    tabs={tabs}
                    sceneInset={newSceneLayout}
                />
            </SceneContent>
        </BindLogic>
    )
}
