import { render } from '@testing-library/react'

import { type ExperimentRecordingModes } from 'scenes/experiments/ExperimentView/experimentRecordingModes'

import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
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
    defaultMode: 'fired_all',
    menuItems: [
        { mode: 'fired_all', label: 'Fired purchase', tooltip: '', disabledReason: null },
        { mode: 'no_metric_activity', label: "Didn't fire purchase", tooltip: '', disabledReason: null },
    ],
    ...overrides,
})

describe('VariantRecordingsButton', () => {
    it.each([
        {
            case: 'a metric the tab accepts links straight to its default population',
            modes: modes({}),
            expectedHref: expect.stringContaining('metric_filter=fired_all'),
            expectedDisabled: 'false',
        },
        {
            // Without this the one click opens the variant's whole list under a label that promises
            // the metric's population, which is the question the row was asked.
            case: 'a metric the tab would drop disables the one-click link',
            modes: modes({
                metricSelectable: false,
                unselectableReason: 'Retention metrics cannot be matched to recordings.',
                defaultMode: null,
            }),
            expectedHref: null,
            expectedDisabled: 'true',
        },
    ])('$case', ({ modes: recordingModes, expectedHref, expectedDisabled }) => {
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

        const button = container.querySelector('[data-attr="experiment-metrics-view-recordings"]')

        expect(button?.getAttribute('aria-disabled')).toEqual(expectedDisabled)
        expect(button?.getAttribute('href')).toEqual(expectedHref)
        // The caret keeps offering the variant's whole list, named, even when the metric is dropped.
        expect(container.querySelector('[data-attr="experiment-metrics-recordings-menu"]')).not.toBeNull()
    })
})
