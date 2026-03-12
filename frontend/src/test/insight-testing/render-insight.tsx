import { render } from '@testing-library/react'
import { useState } from 'react'

import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'

import { resetCapturedCharts } from './chartjs-mock'
import { setupInsightMocks, type MockResponse, type SetupMocksOptions } from './mocks'

export const INSIGHT_TEST_KEY = 'test-harness'
export const INSIGHT_TEST_ID = `new-AdHoc.InsightViz.${INSIGHT_TEST_KEY}`

export function buildTrendsQuery(overrides?: Partial<TrendsQuery>): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
        ...overrides,
    }
}

export interface RenderInsightProps {
    query?: TrendsQuery
    showFilters?: boolean
    mocks?: SetupMocksOptions
    mockResponses?: MockResponse[]
}

function InsightWrapper({ query, showFilters = false }: { query: TrendsQuery; showFilters: boolean }): JSX.Element {
    const [vizQuery, setVizQuery] = useState<InsightVizNode>({
        kind: NodeKind.InsightVizNode,
        source: query,
        showFilters,
        showHeader: showFilters,
        full: showFilters,
    })

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { InsightViz } = require('~/queries/nodes/InsightViz/InsightViz')

    return <InsightViz uniqueKey={INSIGHT_TEST_KEY} query={vizQuery} setQuery={setVizQuery} />
}

export function renderInsight(props: RenderInsightProps = {}): ReturnType<typeof render> {
    resetCapturedCharts()

    setupInsightMocks({
        ...props.mocks,
        mockResponses: props.mockResponses,
    })

    return render(<InsightWrapper query={props.query ?? buildTrendsQuery()} showFilters={props.showFilters ?? false} />)
}
