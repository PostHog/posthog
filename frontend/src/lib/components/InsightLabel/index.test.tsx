import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { ActionFilter } from '~/types'

import { InsightLabel } from './index'

const HOGQL_EXPRESSION = 'avg(properties.usd_amount)'

function hogqlAction(overrides: Partial<ActionFilter> = {}): ActionFilter {
    return {
        id: '$pageview',
        name: '$pageview',
        type: 'events',
        order: 0,
        math: 'hogql',
        math_hogql: HOGQL_EXPRESSION,
        ...overrides,
    } as ActionFilter
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

    it('hides the SQL expression tag when the flag is on, the series is named, and math is hogql', () => {
        renderLabel({ action: hogqlAction({ custom_name: 'Revenue' }), hideHogQLTagWhenCustomName: true })

        expect(screen.queryByText(HOGQL_EXPRESSION)).not.toBeInTheDocument()
    })

    it('keeps the SQL expression tag by default (opt-in), even with a custom name', () => {
        renderLabel({ action: hogqlAction({ custom_name: 'Revenue' }) })

        expect(screen.getByText(HOGQL_EXPRESSION)).toBeInTheDocument()
    })

    it('keeps the SQL expression tag when the flag is on but the series has no custom name', () => {
        renderLabel({ action: hogqlAction(), hideHogQLTagWhenCustomName: true })

        expect(screen.getByText(HOGQL_EXPRESSION)).toBeInTheDocument()
    })

    it('does not affect non-hogql math tags — a named sum series still shows its tag', () => {
        renderLabel({
            action: hogqlAction({ custom_name: 'Revenue', math: 'sum', math_property: 'usd_amount' }),
            hideHogQLTagWhenCustomName: true,
        })

        expect(screen.getByText('Sum')).toBeInTheDocument()
    })
})
