import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { ensureJsdom, getHogChart, waitForHogChartTooltip } from '@posthog/quill-charts/testing'

import { StackedBar, type StackedBarSegment } from './StackedBar'

ensureJsdom()

const segments: StackedBarSegment[] = [
    { count: 20, label: 'Responses', colorClass: 'bg-success' },
    { count: 60, label: 'Dismissed without answers', colorClass: 'bg-warning' },
    { count: 20, label: 'Unanswered', colorClass: 'bg-muted' },
]

describe('StackedBar', () => {
    afterEach(cleanup)

    it.each([
        [segments, '20 (20.0%)'],
        [[{ ...segments[0], tooltip: '20 unique users (20.0%)' }, ...segments.slice(1)], '20 unique users (20.0%)'],
    ])('preserves counts and units in percent-chart tooltips', async (data, expected) => {
        const { container } = render(<StackedBar segments={data} size="sm" />)
        const chart = getHogChart(container)
        const rect = chart.element.getBoundingClientRect()
        fireEvent.mouseMove(chart.element, { clientX: rect.width * 0.1, clientY: rect.height / 2 })
        expect(await waitForHogChartTooltip()).toHaveTextContent(expected)
    })

    it('passes raw counts to the NPS value formatter', () => {
        const { container } = render(
            <StackedBar segments={segments} showTooltips={false} barValueFormatter={(count) => `${count} answers`} />
        )
        expect(
            getHogChart(container)
                .valueLabels()
                .map((label) => label.text)
        ).toEqual(['20 answers', '60 answers', '20 answers'])
    })
})
