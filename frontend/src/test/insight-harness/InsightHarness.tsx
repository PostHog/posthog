import { render } from '@testing-library/react'
import { useState } from 'react'

import { useMocks } from '~/mocks/jest'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'

import { resetCapturedCharts } from './chartjs-mock'
import type { MockResponse } from './fixtures'

export const HARNESS_INSIGHT_KEY = 'test-harness'
export const HARNESS_INSIGHT_ID = `new-AdHoc.InsightViz.${HARNESS_INSIGHT_KEY}`

export interface InsightTestHarnessProps {
    query: TrendsQuery
    mockResponses: MockResponse[]
    showFilters?: boolean
}

function InsightTestHarnessInner({ query, showFilters = false }: InsightTestHarnessProps): JSX.Element {
    const [vizQuery, setVizQuery] = useState<InsightVizNode>({
        kind: NodeKind.InsightVizNode,
        source: query,
        showFilters,
    })

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { InsightViz } = require('~/queries/nodes/InsightViz/InsightViz')

    return <InsightViz uniqueKey={HARNESS_INSIGHT_KEY} query={vizQuery} setQuery={setVizQuery} />
}

// eslint-disable-next-line react-hooks/rules-of-hooks -- useMocks is an MSW helper, not a React hook
export function renderInsight(props: InsightTestHarnessProps): ReturnType<typeof render> {
    resetCapturedCharts()

    useMocks({
        post: {
            '/api/environments/:team_id/query': (req) => {
                const body = (req as any).body as Record<string, any>
                const queryBody = body?.query ?? body

                for (const mock of props.mockResponses) {
                    if (mock.match(queryBody)) {
                        return [200, mock.response]
                    }
                }

                return [200, { results: [] }]
            },
        },
    })

    return render(<InsightTestHarnessInner {...props} />)
}
