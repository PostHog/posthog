import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { DashboardPlacement, QueryBasedInsightModel } from '~/types'

import { InsightCard, shouldRenderInsightCardViz } from './InsightCard'

// Storybook bypasses the gate, and the test runner would otherwise look like Storybook.
jest.mock('lib/utils/dom', () => ({
    ...jest.requireActual('lib/utils/dom'),
    inStorybook: () => false,
    inStorybookTestRunner: () => false,
}))

// A chart needs a canvas and a layout, neither of which jsdom has. The gate decides whether the
// viz mounts at all, so a placeholder stands in for the chart itself.
jest.mock('~/queries/Query/Query', () => ({ Query: () => <div /> }))

// The shared jest stub never reports a tile as on screen, because jsdom has no layout.
function stubIntersectionObserver(): void {
    window.IntersectionObserver = class {
        constructor(private callback: IntersectionObserverCallback) {}
        observe(target: Element): void {
            this.callback(
                [{ target, isIntersecting: true, intersectionRatio: 1 } as IntersectionObserverEntry],
                this as unknown as IntersectionObserver
            )
        }
        unobserve(): void {}
        disconnect(): void {}
        takeRecords(): IntersectionObserverEntry[] {
            return []
        }
    } as unknown as typeof IntersectionObserver
}

function setPageHidden(hidden: boolean): void {
    Object.defineProperty(document, 'hidden', { get: () => hidden, configurable: true })
    Object.defineProperty(document, 'visibilityState', {
        get: () => (hidden ? 'hidden' : 'visible'),
        configurable: true,
    })
}

describe('InsightCard', () => {
    beforeEach(() => {
        initKeaTests()
        stubIntersectionObserver()
    })

    afterEach(() => setPageHidden(false))

    it.each([
        {
            name: 'renders a tile in view',
            input: { isStorybook: false, placement: DashboardPlacement.Dashboard, inView: true },
            expected: true,
        },
        {
            name: 'unmounts an offscreen tile',
            input: { isStorybook: false, placement: DashboardPlacement.Dashboard, inView: false },
            expected: false,
        },
        {
            name: 'renders an offscreen export',
            input: { isStorybook: false, placement: DashboardPlacement.Export, inView: false },
            expected: true,
        },
        {
            name: 'renders an offscreen Storybook tile',
            input: { isStorybook: true, placement: DashboardPlacement.Dashboard, inView: false },
            expected: true,
        },
    ])('$name', ({ input, expected }) => {
        expect(shouldRenderInsightCardViz(input)).toBe(expected)
    })

    // A client can report the page as hidden while it keeps painting the dashboard. Gating on that
    // signal left every chart tile on every dashboard showing its header and nothing else.
    it.each([
        { name: 'trend', source: { kind: NodeKind.TrendsQuery, series: [] } },
        { name: 'funnel', source: { kind: NodeKind.FunnelsQuery, series: [] } },
    ])('mounts a $name tile while the page reports itself hidden', ({ source }) => {
        setPageHidden(true)

        const { container } = render(
            <InsightCard
                insight={
                    {
                        short_id: 'card',
                        result: [],
                        query: { kind: NodeKind.InsightVizNode, source },
                    } as unknown as QueryBasedInsightModel
                }
                placement={DashboardPlacement.Dashboard}
                dashboardId={1}
            />
        )

        expect(container.querySelector('.InsightCard__viz')).toBeInTheDocument()
    })
})
