import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'

import { getHogChart, getHogChartTooltip, hoverAtIndex, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SampleDataState, SampleDataVariant } from './SampleDataState'

describe('<SampleDataState />', () => {
    let cleanupJsdom: () => void
    let cleanupRaf: () => void

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:projectId/tasks/': { count: 0, results: [] },
            },
        })
        cleanupJsdom = setupJsdom()
        cleanupRaf = setupSyncRaf()
    })

    afterEach(() => {
        cleanupRaf()
        cleanupJsdom()
        cleanup()
    })

    it.each([
        ['line' as SampleDataVariant, 7],
        ['bar' as SampleDataVariant, 7],
        ['funnel' as SampleDataVariant, 4],
    ])('keeps the made-up %s numbers out of a tooltip on hover', async (variant, pointCount) => {
        const { container } = render(<SampleDataState variant={variant} />)
        const chart = getHogChart(container)
        // Axis ticks appear once the chart commits its scales, which is also when it starts
        // answering hovers - without waiting for them the hovers below would be dropped.
        await waitFor(() => expect(chart.xTicks().length).toBeGreaterThan(0))

        for (let index = 0; index < pointCount; index++) {
            hoverAtIndex(chart.element, index, pointCount)
        }

        expect(getHogChartTooltip()).toBeNull()
    })
})
