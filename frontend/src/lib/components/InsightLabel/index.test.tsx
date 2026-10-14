import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import type { ResultSeries } from 'scenes/insights/utils/resultSeries'

import { EventsNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { HogQLMathType, PropertyMathType } from '~/types'

import { InsightLabel } from './index'

const HOGQL_EXPRESSION = 'avg(properties.usd_amount)'

function hogqlSeries(overrides: Partial<EventsNode> = {}): ResultSeries {
    const node: EventsNode = {
        kind: NodeKind.EventsNode,
        event: '$pageview',
        name: '$pageview',
        math: HogQLMathType.HogQL,
        math_hogql: HOGQL_EXPRESSION,
        ...overrides,
    }
    return {
        order: 0,
        node,
        math: { math: node.math, math_property: node.math_property, math_hogql: node.math_hogql },
    }
}

describe('InsightLabel — hideHogQLTagWhenCustomName', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    function renderLabel(props: Parameters<typeof InsightLabel>[0]): void {
        render(
            <Provider>
                <InsightLabel {...props} />
            </Provider>
        )
    }

    it.each<[string, Partial<EventsNode>]>([
        ['a custom name', { custom_name: 'Revenue' }],
        ['a rename through its name', { name: 'Revenue' }],
    ])('hides the SQL expression tag when the flag is on, the series has %s, and math is hogql', (_, overrides) => {
        renderLabel({ series: hogqlSeries(overrides), hideHogQLTagWhenCustomName: true })

        expect(screen.queryByText(HOGQL_EXPRESSION)).not.toBeInTheDocument()
    })

    it('keeps the SQL expression tag by default (opt-in), even with a custom name', () => {
        renderLabel({ series: hogqlSeries({ custom_name: 'Revenue' }) })

        expect(screen.getByText(HOGQL_EXPRESSION)).toBeInTheDocument()
    })

    it('keeps the SQL expression tag when the flag is on but the series has no custom name', () => {
        renderLabel({ series: hogqlSeries(), hideHogQLTagWhenCustomName: true })

        expect(screen.getByText(HOGQL_EXPRESSION)).toBeInTheDocument()
    })

    it('does not affect non-hogql math tags — a named sum series still shows its tag', () => {
        renderLabel({
            series: hogqlSeries({ custom_name: 'Revenue', math: PropertyMathType.Sum, math_property: 'usd_amount' }),
            hideHogQLTagWhenCustomName: true,
        })

        expect(screen.getByText('Sum')).toBeInTheDocument()
    })
})
