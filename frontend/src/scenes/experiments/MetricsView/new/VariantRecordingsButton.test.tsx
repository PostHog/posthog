import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { type ExperimentRecordingModes } from 'scenes/experiments/ExperimentView/experimentRecordingModes'

import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { VariantRecordingsButton } from './VariantRecordingsButton'

const experiment = { id: 7 } as Experiment

const metric = {
    kind: NodeKind.ExperimentMetric,
    metric_type: ExperimentMetricType.MEAN,
    uuid: 'metric-mean',
    source: { kind: NodeKind.EventsNode, event: 'purchase' },
} as unknown as ExperimentMetric

const modes = (overrides: Partial<ExperimentRecordingModes>): ExperimentRecordingModes => ({
    metricSelectable: true,
    unselectableReason: null,
    unselectableCode: null,
    defaultMode: 'fired_all',
    menuItems: [
        { mode: 'fired_all', label: 'Fired purchase', tooltip: '', disabledReason: null },
        { mode: 'no_metric_activity', label: "Didn't fire purchase", tooltip: '', disabledReason: null },
    ],
    ...overrides,
})

const droppedMetricModes = (): ExperimentRecordingModes =>
    modes({
        metricSelectable: false,
        unselectableReason: 'Retention metrics measure a return visit in a later session.',
        unselectableCode: 'retention',
        defaultMode: null,
        menuItems: [
            {
                mode: 'fired_all',
                label: 'Fired purchase',
                tooltip: '',
                disabledReason: 'Retention metrics measure a return visit in a later session.',
            },
            {
                mode: 'no_metric_activity',
                label: "Didn't fire purchase",
                tooltip: '',
                disabledReason: 'Retention metrics measure a return visit in a later session.',
            },
        ],
    })

/** The whole param set, so a param the link must not carry fails the assertion by being present. */
const linkParams = (element: Element | null): Record<string, string> =>
    Object.fromEntries(new URLSearchParams(element?.getAttribute('href')?.split('?')[1] ?? ''))

const renderButton = (recordingModes: ExperimentRecordingModes): HTMLElement => {
    const { container } = render(
        <VariantRecordingsButton
            experiment={experiment}
            metric={metric}
            variantKey="test"
            isBaseline={false}
            surface="inline"
            modes={recordingModes}
        />
    )
    return container
}

describe('VariantRecordingsButton', () => {
    // Every link here is a `Link`, which routes client-side, so the router has to be mounted or the
    // click throws instead of navigating.
    beforeEach(() => {
        initKeaTests(false)
        router.mount()
    })

    it.each([
        {
            case: 'a metric the tab accepts links straight to its default population',
            modes: modes({}),
            expectedParams: {
                tab: 'recordings',
                variant: 'test',
                metric_uuid: 'metric-mean',
                metric_filter: 'fired_all',
                entry: 'results_button',
            },
        },
        {
            // A refused click left the row a dead control, so the fallback opens the variant's whole
            // list and hands the tab the reason its metric filter is missing.
            case: 'a metric the tab would drop opens every recording of the variant, with the reason',
            modes: droppedMetricModes(),
            expectedParams: {
                tab: 'recordings',
                variant: 'test',
                entry: 'results_button',
                metric_unavailable: 'retention',
            },
        },
    ])('$case', ({ modes: recordingModes, expectedParams }) => {
        const container = renderButton(recordingModes)

        const button = container.querySelector('[data-attr="experiment-metrics-view-recordings"]')

        expect(button?.getAttribute('aria-disabled')).toEqual('false')
        expect(linkParams(button)).toEqual(expectedParams)
        // The caret keeps offering the variant's whole list, named, even when the metric is dropped.
        expect(container.querySelector('[data-attr="experiment-metrics-recordings-menu"]')).not.toBeNull()
    })

    it('keeps the metric modes refused in the menu, and explains nothing the menu already names', async () => {
        // The two metric modes name a population the tab can't produce for this metric, so they stay
        // refused. "All recordings of this variant" says what it opens, so the tab must not caption
        // it with an explanation the reader never asked for, and the report must not count it as a
        // filter taken away.
        const captureSpy = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
        const container = renderButton(droppedMetricModes())

        await userEvent.click(container.querySelector('[data-attr="experiment-metrics-recordings-menu"]')!)

        const item = (mode: string): Element | null =>
            document.querySelector(`[data-attr="experiment-metrics-recordings-menu-${mode}"]`)
        expect(item('fired_all')?.getAttribute('aria-disabled')).toEqual('true')
        expect(item('no_metric_activity')?.getAttribute('aria-disabled')).toEqual('true')
        expect(linkParams(item('all'))).toEqual({ tab: 'recordings', variant: 'test', entry: 'results_menu' })

        await userEvent.click(item('all')!)
        expect(captureSpy).toHaveBeenLastCalledWith(
            'viewed recordings from experiment',
            expect.objectContaining({ trigger: 'menu', metric_unavailable_reason: null })
        )
    })
})
