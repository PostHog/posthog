import { Card, Col, Row } from 'antd'
import { InsightDisplayConfig } from 'scenes/insights/InsightTabs/InsightDisplayConfig'
import { FunnelCanvasLabel } from 'scenes/funnels/FunnelCanvasLabel'
import { ComputationTimeWithRefresh } from 'scenes/insights/ComputationTimeWithRefresh'
import { FunnelVizType, ViewType } from '~/types'
import { TrendInsight } from 'scenes/trends/Trends'
import { FunnelInsight } from 'scenes/insights/FunnelInsight'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { Paths } from 'scenes/paths/Paths'
import { ACTIONS_BAR_CHART_VALUE, ACTIONS_TABLE, FEATURE_FLAGS, FUNNEL_VIZ, FunnelLayout } from 'lib/constants'
import { People } from 'scenes/funnels/FunnelPeople'
import { FunnelStepTable } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepTable'
import { BindLogic, useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightsTable } from 'scenes/insights/InsightsTable'
import React from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { annotationsLogic } from 'lib/components/Annotations'
import { router } from 'kea-router'
import {
    ErrorMessage,
    FunnelEmptyState,
    FunnelInvalidExclusionFiltersEmptyState,
    FunnelInvalidFiltersEmptyState,
    TimeOut,
} from 'scenes/insights/EmptyStates'
import { Loading } from 'lib/utils'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import clsx from 'clsx'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PathCanvasLabel } from 'scenes/paths/PathsLabel'
import { FunnelCorrelation } from './FunnelCorrelation'

const VIEW_MAP = {
    [`${ViewType.TRENDS}`]: <TrendInsight view={ViewType.TRENDS} />,
    [`${ViewType.STICKINESS}`]: <TrendInsight view={ViewType.STICKINESS} />,
    [`${ViewType.LIFECYCLE}`]: <TrendInsight view={ViewType.LIFECYCLE} />,
    [`${ViewType.SESSIONS}`]: <TrendInsight view={ViewType.SESSIONS} />,
    [`${ViewType.FUNNELS}`]: <FunnelInsight />,
    [`${ViewType.RETENTION}`]: <RetentionContainer />,
    [`${ViewType.PATHS}`]: <Paths />,
}

export function InsightContainer(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        hashParams: { fromItem },
    } = useValues(router)
    const { clearAnnotationsToCreate } = useActions(annotationsLogic({ pageKey: fromItem }))
    const { annotationsToCreate } = useValues(annotationsLogic({ pageKey: fromItem }))
    const {
        insightProps,
        lastRefresh,
        isLoading,
        activeView,
        loadedView,
        filters,
        insightMode,
        showTimeoutMessage,
        showErrorMessage,
        insightLoading,
    } = useValues(insightLogic)
    const { areFiltersValid, isValidFunnel, areExclusionFiltersValid } = useValues(funnelLogic(insightProps))

    // Empty states that completely replace the graph
    const BlockingEmptyState = (() => {
        if (activeView !== loadedView) {
            return <Loading />
        }
        // Insight specific empty states - note order is important here
        if (loadedView === ViewType.FUNNELS) {
            if (!areFiltersValid) {
                return <FunnelInvalidFiltersEmptyState />
            }
            if (!areExclusionFiltersValid) {
                return <FunnelInvalidExclusionFiltersEmptyState />
            }
            if (!isValidFunnel && !(insightLoading || isLoading)) {
                return <FunnelEmptyState />
            }
        }

        // Insight agnostic empty states
        if (showErrorMessage) {
            return <ErrorMessage />
        }
        if (showTimeoutMessage) {
            return <TimeOut isLoading={isLoading} />
        }

        return null
    })()

    // Empty states that can coexist with the graph (e.g. Loading)
    const CoexistingEmptyState = (() => {
        if (isLoading || insightLoading) {
            return <Loading />
        }
        return null
    })()

    function renderTable(): JSX.Element | null {
        if (
            !preflight?.is_clickhouse_enabled &&
            !showErrorMessage &&
            !showTimeoutMessage &&
            areFiltersValid &&
            activeView === ViewType.FUNNELS &&
            filters?.display === FUNNEL_VIZ
        ) {
            return <People />
        }

        if (
            preflight?.is_clickhouse_enabled &&
            activeView === ViewType.FUNNELS &&
            !showErrorMessage &&
            !showTimeoutMessage &&
            areFiltersValid &&
            filters.funnel_viz_type === FunnelVizType.Steps &&
            (!featureFlags[FEATURE_FLAGS.FUNNEL_VERTICAL_BREAKDOWN] || filters?.layout === FunnelLayout.horizontal)
        ) {
            return <FunnelStepTable />
        }
        if (
            (!filters.display ||
                (filters?.display !== ACTIONS_TABLE && filters?.display !== ACTIONS_BAR_CHART_VALUE)) &&
            (activeView === ViewType.TRENDS || activeView === ViewType.SESSIONS)
        ) {
            /* InsightsTable is loaded for all trend views (except below), plus the sessions view.
    Exclusions:
        1. Table view. Because table is already loaded anyways in `Trends.tsx` as the main component.
        2. Bar value chart. Because this view displays data in completely different dimensions.
    */
            return (
                <Card style={{ marginTop: 8 }}>
                    <BindLogic logic={trendsLogic} props={insightProps}>
                        <h3 className="l3">Details table</h3>
                        <InsightsTable showTotalCount={activeView !== ViewType.SESSIONS} />
                    </BindLogic>
                </Card>
            )
        }

        return null
    }

    return (
        <>
            {/* These are filters that are reused between insight features. They each have generic logic that updates the url */}
            <Card
                title={
                    <InsightDisplayConfig
                        activeView={activeView as ViewType}
                        insightMode={insightMode}
                        filters={filters}
                        annotationsToCreate={annotationsToCreate}
                        clearAnnotationsToCreate={clearAnnotationsToCreate}
                    />
                }
                data-attr="insights-graph"
                className={clsx('insights-graph-container', {
                    funnels: activeView === ViewType.FUNNELS,
                })}
            >
                <div>
                    <Row
                        className={clsx('insights-graph-header', {
                            funnels: activeView === ViewType.FUNNELS,
                        })}
                        align="middle"
                        justify="space-between"
                        style={{
                            marginTop: -8,
                            marginBottom: 16,
                        }}
                    >
                        <Col>
                            <FunnelCanvasLabel />
                            <PathCanvasLabel />
                        </Col>
                        {lastRefresh && <ComputationTimeWithRefresh />}
                    </Row>
                    {!BlockingEmptyState && CoexistingEmptyState}
                    <div style={{ display: 'block' }}>
                        {!!BlockingEmptyState ? BlockingEmptyState : VIEW_MAP[activeView]}
                    </div>
                </div>
            </Card>
            {renderTable()}

            {preflight?.is_clickhouse_enabled &&
            activeView === ViewType.FUNNELS &&
            featureFlags[FEATURE_FLAGS.CORRELATION_ANALYSIS] ? (
                <FunnelCorrelation />
            ) : null}
        </>
    )
}
