import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'

import { Query } from './Query'

const insightVizQueryCalls: InsightVizNode[] = []

jest.mock('~/queries/nodes/InsightViz/InsightViz', () => ({
    InsightViz: (props: { query: InsightVizNode }) => {
        insightVizQueryCalls.push(props.query)
        return <div data-testid="insight-viz" />
    },
    insightVizDataNodeKey: () => 'test-key',
}))

jest.mock('~/layout/ErrorBoundary', () => ({
    ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

function makeInsightVizQuery(modifiers?: Record<string, unknown>): InsightVizNode {
    return {
        kind: NodeKind.InsightVizNode as const,
        source: {
            kind: NodeKind.TrendsQuery as const,
            series: [{ kind: NodeKind.EventsNode as const, event: '$pageview', name: '$pageview' }],
            ...(modifiers ? { modifiers } : {}),
        },
    }
}

describe('Query', () => {
    beforeEach(() => {
        insightVizQueryCalls.length = 0
    })

    it('immediately uses propsQuery on re-render when controlled via setQuery (no stale localQuery)', () => {
        const originalQuery = makeInsightVizQuery()
        const setQuery = jest.fn()

        const { rerender } = render(<Query query={originalQuery} setQuery={setQuery} uniqueKey="test" />)

        insightVizQueryCalls.length = 0

        const updatedQuery = makeInsightVizQuery({
            personsOnEventsMode: 'person_id_override_properties_joined',
        })
        rerender(<Query query={updatedQuery} setQuery={setQuery} uniqueKey="test" />)

        expect(insightVizQueryCalls[0]).toBe(updatedQuery)
    })

    it('uses propsQuery when readOnly is true', () => {
        const query = makeInsightVizQuery({
            personsOnEventsMode: 'person_id_override_properties_joined',
        })

        render(<Query query={query} readOnly uniqueKey="test" />)

        expect(insightVizQueryCalls[0]).toBe(query)
    })

    it('syncs updated propsQuery via useEffect when uncontrolled', () => {
        const originalQuery = makeInsightVizQuery()

        const { rerender } = render(<Query query={originalQuery} uniqueKey="test" />)

        insightVizQueryCalls.length = 0

        const updatedQuery = makeInsightVizQuery({
            personsOnEventsMode: 'person_id_override_properties_joined',
        })
        rerender(<Query query={updatedQuery} uniqueKey="test" />)

        const lastCall = insightVizQueryCalls[insightVizQueryCalls.length - 1]
        expect(lastCall).toBe(updatedQuery)
    })

    it('returns null for null query', () => {
        const { container } = render(<Query query={null} uniqueKey="test" />)
        expect(container.innerHTML).toBe('')
    })
})
