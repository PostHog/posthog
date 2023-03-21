import './Insight.scss'
import { useEffect } from 'react'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightLogic } from './insightLogic'
import { insightCommandLogic } from './insightCommandLogic'
import { insightDataLogic } from './insightDataLogic'
import { InsightShortId, InsightType, ItemMode } from '~/types'
import { InsightsNav } from './InsightNav/InsightsNav'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { EditorFilters } from './EditorFilters/EditorFilters'
import clsx from 'clsx'
import { Query } from '~/queries/Query/Query'
import { InsightPageHeader } from 'scenes/insights/InsightPageHeader'
import { containsHogQLQuery } from '~/queries/utils'
import { OpenEditorButton } from '~/queries/nodes/Node/OpenEditorButton'
import { Link } from 'lib/lemon-ui/Link'

export interface InsightSceneProps {
    insightId: InsightShortId | 'new'
}

export function Insight({ insightId }: InsightSceneProps): JSX.Element {
    // insightSceneLogic
    const { insightMode } = useValues(insightSceneLogic)

    // insightLogic
    const logic = insightLogic({ dashboardItemId: insightId || 'new' })
    const {
        insightProps,
        insightLoading,
        filtersKnown,
        filters,
        isUsingDataExploration,
        erroredQueryId,
        isFilterBasedInsight,
    } = useValues(logic)
    const { reportInsightViewedForRecentInsights, abortAnyRunningQuery, loadResults } = useActions(logic)

    // insightDataLogic
    const { query, isQueryBasedInsight, showQueryEditor } = useValues(insightDataLogic(insightProps))
    const { setQuery } = useActions(insightDataLogic(insightProps))

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))

    useEffect(() => {
        reportInsightViewedForRecentInsights()
    }, [insightId])

    useEffect(() => {
        // if users navigate away from insights then we may cancel an API call
        // and when they come back they may see an error state, so clear it
        if (!!erroredQueryId) {
            loadResults()
        }
        return () => {
            // request cancellation of any running queries when this component is no longer in the dom
            abortAnyRunningQuery()
        }
    }, [])
    // if this is a non-viz query-based insight e.g. an events table then don't show the insight editing chrome
    const showFilterEditing = isFilterBasedInsight

    // Show the skeleton if loading an insight for which we only know the id
    // This helps with the UX flickering and showing placeholder "name" text.
    if (insightId !== 'new' && insightLoading && !filtersKnown) {
        return <InsightSkeleton />
    }

    const actuallyShowQueryEditor =
        isUsingDataExploration &&
        insightMode === ItemMode.Edit &&
        ((isQueryBasedInsight && !containsHogQLQuery(query)) || showQueryEditor)

    const insightScene = (
        <div className={'insights-page'}>
            <InsightPageHeader insightLogicProps={insightProps} />

            {insightMode === ItemMode.Edit && <InsightsNav />}

            {isUsingDataExploration ? (
                <>
                    {actuallyShowQueryEditor && isQueryBasedInsight && query ? (
                        <div className="mb-2">
                            Buttons like{' '}
                            <div className="inline-block">
                                <OpenEditorButton query={query} type="secondary" size="small" className="ml-1 mr-1" />
                            </div>{' '}
                            open any part of PostHog as a new insight. Read the{' '}
                            <Link
                                to="https://github.com/posthog/posthog/blob/master/frontend/src/queries/schema.ts"
                                target="_blank"
                            >
                                schema.ts
                            </Link>{' '}
                            source for documentation.
                        </div>
                    ) : null}
                    <Query
                        query={query}
                        setQuery={insightMode === ItemMode.Edit ? setQuery : undefined}
                        context={{
                            showOpenEditorButton: false,
                            showQueryEditor: actuallyShowQueryEditor,
                        }}
                    />
                </>
            ) : (
                <>
                    <div
                        className={clsx('insight-wrapper', {
                            'insight-wrapper--singlecolumn': filters.insight === InsightType.FUNNELS,
                        })}
                    >
                        <EditorFilters
                            insightProps={insightProps}
                            showing={showFilterEditing && insightMode === ItemMode.Edit}
                        />
                        <div className="insights-container" data-attr="insight-view">
                            <InsightContainer insightMode={insightMode} />
                        </div>
                    </div>
                </>
            )}
        </div>
    )

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            {insightScene}
        </BindLogic>
    )
}
