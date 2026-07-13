import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'

import {
    createDefaultTooltipAccessor,
    getHogChart,
    hoverUntilTooltip,
    setupJsdom,
    setupSyncRaf,
} from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { Sparkline, SparklineProps } from './Sparkline'

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

function renderSparkline(props: SparklineProps, { quillFlag = true }: { quillFlag?: boolean } = {}): void {
    initKeaTests()
    const ffLogic = featureFlagLogic()
    ffLogic.mount()
    // Always set the flag explicitly — the featureFlags reducer is kea-persisted to localStorage,
    // which survives across tests in this file, so an unset flag would leak the previous test's value.
    ffLogic.actions.setFeatureFlags([FEATURE_FLAGS.QUILL_SPARKLINE], { [FEATURE_FLAGS.QUILL_SPARKLINE]: quillFlag })
    render(<Sparkline {...props} />)
}

// Quill charts label their main canvas for a11y and add an aria-hidden hover-overlay canvas;
// the legacy Chart.js canvas carries neither attribute.
const quillCanvas = (): Element | null => document.querySelector('canvas[aria-label]')
const legacyCanvas = (): Element | null => document.querySelector('canvas:not([aria-label]):not([aria-hidden])')

const DATA = [10, 5, 3, 30]
const LABELS = ['Mon', 'Tue', 'Wed', 'Thu']

describe('Sparkline', () => {
    it('renders via quill when the flag is on and only simple props are used', () => {
        renderSparkline({ data: DATA, labels: LABELS })
        expect(quillCanvas()).toBeTruthy()
        expect(legacyCanvas()).toBeNull()
    })

    it('renders via Chart.js when the flag is off', () => {
        renderSparkline({ data: DATA, labels: LABELS }, { quillFlag: false })
        expect(legacyCanvas()).toBeTruthy()
        expect(quillCanvas()).toBeNull()
    })

    it.each<{ feature: string; props: Partial<SparklineProps> }>([
        { feature: 'onSelectionChange', props: { onSelectionChange: () => {} } },
        { feature: 'highlightedRange', props: { highlightedRange: { xMin: 'Mon', xMax: 'Tue' } } },
        { feature: 'incompleteBars', props: { incompleteBars: { indices: [3] } } },
        { feature: 'referenceLines', props: { referenceLines: [{ value: 20 }] } },
        { feature: 'withXScale', props: { withXScale: (x) => x } },
        { feature: 'withYScale', props: { withYScale: (y) => y } },
    ])('keeps Chart.js when $feature is passed, even with the flag on', ({ props }) => {
        renderSparkline({ data: DATA, labels: LABELS, ...props })
        expect(legacyCanvas()).toBeTruthy()
        expect(quillCanvas()).toBeNull()
    })

    it.each<{ shape: string; data: SparklineProps['data']; seriesCount: number }>([
        { shape: 'a flat number array', data: DATA, seriesCount: 1 },
        {
            shape: 'multiple time series',
            data: [
                { name: 'success', values: [1, 2, 3, 4], color: 'success' },
                { name: 'failure', values: [4, 3, 2, 1], color: 'danger' },
            ],
            seriesCount: 2,
        },
    ])('normalizes $shape into $seriesCount quill series', ({ data, seriesCount }) => {
        renderSparkline({ data, labels: LABELS })
        expect(getHogChart().seriesCount).toBe(seriesCount)
    })

    it('wires tooltip formatting and zero-row filtering through to the quill tooltip', async () => {
        // Line type: bar charts hit-test the cursor against filled segments before showing a
        // tooltip, while lines surface all series — and the tooltip wiring under test is shared.
        renderSparkline({
            data: [
                { name: 'volume', values: [10, 0, 3, 30] },
                { name: 'errors', values: [2, 0, 0, 1] },
            ],
            labels: LABELS,
            type: 'line',
            hideZerosInTooltip: true,
            renderLabel: (label) => `Day: ${label}`,
            renderTooltipValue: (value) => `$${value.toFixed(2)}`,
        })
        const chart = getHogChart()

        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 2, LABELS.length))
        // The portal mounts before its content commits, so poll until the header lands.
        await waitFor(() => expect(tooltip.label()).toBe('Day: Wed'))
        expect(tooltip.value('volume')).toBe('$3.00')
        expect(tooltip.rows()).toEqual(['volume']) // the zero 'errors' row is hidden
    })

    it('shows a skeleton instead of a chart while loading', () => {
        renderSparkline({ data: DATA, labels: LABELS, loading: true })
        expect(document.querySelector('canvas')).toBeNull()
        expect(document.querySelector('.LemonSkeleton')).toBeTruthy()
    })
})
