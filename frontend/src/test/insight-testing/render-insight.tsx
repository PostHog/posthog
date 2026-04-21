import { render } from '@testing-library/react'
import { useState } from 'react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { initKeaTests } from '../init'
import { resetCapturedCharts } from './chartjs-mock'
import { setupInsightMocks, type SetupMocksOptions } from './mocks'

export const INSIGHT_TEST_KEY = 'test-harness'
export const INSIGHT_TEST_ID = `new-AdHoc.InsightViz.${INSIGHT_TEST_KEY}`

export function buildTrendsQuery(overrides?: Partial<TrendsQuery>): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
        ...overrides,
    }
}

/** Sets up Kea context, mounts common logics, and configures insight API mocks. */
function setupTestEnvironment(mocks?: SetupMocksOptions, featureFlags?: Record<string, string | boolean>): void {
    resetCapturedCharts()

    initKeaTests()
    actionsModel.mount()
    groupsModel.mount()

    if (featureFlags && Object.keys(featureFlags).length > 0) {
        const ffLogic = featureFlagLogic()
        ffLogic.mount()
        ffLogic.actions.setFeatureFlags(Object.keys(featureFlags), featureFlags)
    }

    setupInsightMocks(mocks)
}

export interface RenderWithInsightsProps {
    component: React.ReactElement
    mocks?: SetupMocksOptions
    featureFlags?: Record<string, string | boolean>
}

/** Render any component with insight mocks and Kea logics ready. */
export function renderWithInsights(props: RenderWithInsightsProps): ReturnType<typeof render> {
    setupTestEnvironment(props.mocks, props.featureFlags)
    return render(props.component)
}

export interface RenderInsightProps {
    query?: TrendsQuery
    showFilters?: boolean
    mocks?: SetupMocksOptions
    featureFlags?: Record<string, string | boolean>
    context?: QueryContext<InsightVizNode>
}

function InsightWrapper({
    query,
    showFilters = false,
    context,
}: {
    query: TrendsQuery
    showFilters: boolean
    context?: QueryContext<InsightVizNode>
}): JSX.Element {
    const [vizQuery, setVizQuery] = useState<InsightVizNode>({
        kind: NodeKind.InsightVizNode,
        source: query,
        showFilters,
        showHeader: showFilters,
        full: showFilters,
    })

    // Dynamic require to break a circular-dependency cycle that causes Jest to fail
    // with static imports. Node's module cache means this is only resolved once.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { InsightViz } = require('~/queries/nodes/InsightViz/InsightViz')

    return <InsightViz uniqueKey={INSIGHT_TEST_KEY} query={vizQuery} setQuery={setVizQuery} context={context} />
}

export function renderInsight(props: RenderInsightProps = {}): ReturnType<typeof render> {
    setupTestEnvironment(props.mocks, props.featureFlags)

    return render(
        <InsightWrapper
            query={props.query ?? buildTrendsQuery()}
            showFilters={props.showFilters ?? true}
            context={props.context}
        />
    )
}
