import { render } from '@testing-library/react'
import { useState } from 'react'

import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'

import { resetCapturedCharts } from './chartjs-mock'
import { setupInsightMocks, type MockResponse, type SetupMocksOptions } from './mocks'

export const HARNESS_INSIGHT_KEY = 'test-harness'
export const HARNESS_INSIGHT_ID = `new-AdHoc.InsightViz.${HARNESS_INSIGHT_KEY}`

export function buildTrendsQuery(overrides?: Partial<TrendsQuery>): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
        ...overrides,
    }
}

export interface InsightTestHarnessProps {
    query?: TrendsQuery
    showFilters?: boolean
    mocks?: SetupMocksOptions
    mockResponses?: MockResponse[]
}

function InsightTestHarnessInner({
    query,
    showFilters = false,
}: {
    query: TrendsQuery
    showFilters: boolean
}): JSX.Element {
    const [vizQuery, setVizQuery] = useState<InsightVizNode>({
        kind: NodeKind.InsightVizNode,
        source: query,
        showFilters,
        showHeader: showFilters,
        full: showFilters,
    })

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { InsightViz } = require('~/queries/nodes/InsightViz/InsightViz')

    return <InsightViz uniqueKey={HARNESS_INSIGHT_KEY} query={vizQuery} setQuery={setVizQuery} />
}

export function renderInsight(props: InsightTestHarnessProps = {}): ReturnType<typeof render> {
    resetCapturedCharts()

    setupInsightMocks({
        ...props.mocks,
        mockResponses: props.mockResponses,
    })

    return render(
        <InsightTestHarnessInner query={props.query ?? buildTrendsQuery()} showFilters={props.showFilters ?? false} />
    )
}
