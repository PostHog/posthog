import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'

import { FUNNEL_SERVER_SIDE_COMPLETION_REASON } from '../../utils'
import {
    DATA_WAREHOUSE_UNLINKABLE_REASON,
    METRIC_UNLINKABLE_REASON,
    RETENTION_UNLINKABLE_REASON,
} from '../../viewRecordingsLinkabilityLogic'
import { getResultRowRecordingLinks } from './resultRowRecordingLinks'

const meanMetric = (source: Record<string, unknown>): ExperimentMetric =>
    ({
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.MEAN,
        uuid: 'metric-mean',
        source,
    }) as unknown as ExperimentMetric

const funnelMetric = (series: Record<string, unknown>[]): ExperimentMetric =>
    ({
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.FUNNEL,
        uuid: 'metric-funnel',
        series,
    }) as unknown as ExperimentMetric

const PURCHASE = meanMetric({ kind: NodeKind.EventsNode, event: 'purchase' })
const CHECKOUT_FUNNEL = funnelMetric([
    { kind: NodeKind.EventsNode, event: 'checkout_started' },
    { kind: NodeKind.EventsNode, event: 'checkout_finished' },
])

describe('getResultRowRecordingLinks', () => {
    it.each([
        {
            case: 'a mean metric names its event and asks the two fired modes',
            metric: PURCHASE,
            expected: [
                { label: 'Fired purchase', metricFilterMode: 'fired_all', disabledReason: null },
                { label: "Didn't fire purchase", metricFilterMode: 'no_metric_activity', disabledReason: null },
            ],
        },
        {
            case: 'a ratio metric names its numerator event',
            metric: {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.RATIO,
                uuid: 'metric-ratio',
                numerator: { kind: NodeKind.EventsNode, event: 'revenue' },
                denominator: { kind: NodeKind.EventsNode, event: '$pageview' },
            } as unknown as ExperimentMetric,
            expected: [
                { label: 'Fired revenue', metricFilterMode: 'fired_all', disabledReason: null },
                { label: "Didn't fire revenue", metricFilterMode: 'no_metric_activity', disabledReason: null },
            ],
        },
        {
            // An action matches several events and names none of them, so a label built from its
            // id would read as an event the project doesn't have.
            case: 'an action source falls back to the generic label',
            metric: meanMetric({ kind: NodeKind.ActionsNode, id: 12 }),
            expected: [
                { label: 'Fired metric events', metricFilterMode: 'fired_all', disabledReason: null },
                { label: "Didn't fire metric events", metricFilterMode: 'no_metric_activity', disabledReason: null },
            ],
        },
        {
            case: 'a funnel asks the two funnel modes',
            metric: CHECKOUT_FUNNEL,
            expected: [
                { label: 'Finished funnel', metricFilterMode: 'funnel_completed', disabledReason: null },
                { label: "Didn't finish funnel", metricFilterMode: 'funnel_dropoff', disabledReason: null },
            ],
        },
    ])('$case', ({ metric, expected }) => {
        // The mode decides which population the recordings tab opens on, so a mode paired with the
        // wrong label sends the viewer to the opposite set of people.
        expect(getResultRowRecordingLinks(metric, new Set())).toMatchObject(expected)
    })

    it.each([
        {
            case: 'a metric with no uuid, which the tab cannot select',
            metric: { ...PURCHASE, uuid: undefined } as ExperimentMetric,
            unlinkable: [],
            expected: "This metric can't be selected on the Recordings tab.",
        },
        {
            case: 'a metric whose only event is captured server-side',
            metric: PURCHASE,
            unlinkable: ['purchase'],
            expected: METRIC_UNLINKABLE_REASON,
        },
        {
            case: 'a retention metric, which no single recording can show',
            metric: {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.RETENTION,
                uuid: 'metric-retention',
                start_event: { kind: NodeKind.EventsNode, event: '$pageview' },
                completion_event: { kind: NodeKind.EventsNode, event: '$pageview' },
            } as unknown as ExperimentMetric,
            unlinkable: [],
            expected: RETENTION_UNLINKABLE_REASON,
        },
        {
            case: 'a metric measured only in the data warehouse',
            metric: meanMetric({ kind: NodeKind.ExperimentDataWarehouseNode, table_name: 'stripe_charges' }),
            unlinkable: [],
            expected: DATA_WAREHOUSE_UNLINKABLE_REASON,
        },
        {
            // The other steps stay matchable, so the metric is fine elsewhere. Both funnel modes
            // read the last step, so a completion no recording can show disables the pair.
            case: 'a funnel finishing on a server-side step',
            metric: CHECKOUT_FUNNEL,
            unlinkable: ['checkout_finished'],
            expected: FUNNEL_SERVER_SIDE_COMPLETION_REASON,
        },
    ])('disables both links for $case', ({ metric, unlinkable, expected }) => {
        // A link that lands on a list which can only be empty is worse than no link: the viewer
        // reads the empty list as the variant having no recordings.
        const links = getResultRowRecordingLinks(metric, new Set(unlinkable))
        expect(links.map((link) => link.disabledReason)).toEqual([expected, expected])
    })
})
