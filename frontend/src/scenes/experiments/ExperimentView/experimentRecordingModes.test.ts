import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'

import { FUNNEL_DATA_WAREHOUSE_COMPLETION_REASON, FUNNEL_SERVER_SIDE_COMPLETION_REASON } from '../utils'
import {
    DATA_WAREHOUSE_UNLINKABLE_REASON,
    METRIC_UNLINKABLE_REASON,
    RETENTION_UNLINKABLE_REASON,
} from '../viewRecordingsLinkabilityLogic'
import { METRIC_WITHOUT_UUID_REASON, getMetricRecordingModes } from './experimentRecordingModes'

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

const ratioMetric = (numerator: Record<string, unknown>, denominator: Record<string, unknown>): ExperimentMetric =>
    ({
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.RATIO,
        uuid: 'metric-ratio',
        numerator,
        denominator,
    }) as unknown as ExperimentMetric

const event = (name: string): Record<string, unknown> => ({ kind: NodeKind.EventsNode, event: name })

describe('getMetricRecordingModes', () => {
    it.each([
        {
            case: 'a funnel whose last step can be matched opens the finished half first',
            metric: funnelMetric([event('checkout_started'), event('checkout_finished')]),
            unlinkable: [],
            expected: {
                metricSelectable: true,
                defaultMode: 'funnel_completed',
                labels: ['Finished funnel', "Didn't finish funnel"],
                disabledReasons: [null, null],
            },
        },
        {
            // The earlier steps stay matchable, so the metric itself is still selectable. Only the
            // two modes that read the last step are refused.
            case: 'a funnel finishing on a server-side step falls back to the fired mode',
            metric: funnelMetric([event('checkout_started'), event('checkout_finished')]),
            unlinkable: ['checkout_finished'],
            expected: {
                metricSelectable: true,
                defaultMode: 'fired_all',
                labels: ['Finished funnel', "Didn't finish funnel"],
                disabledReasons: [FUNNEL_SERVER_SIDE_COMPLETION_REASON, FUNNEL_SERVER_SIDE_COMPLETION_REASON],
            },
        },
        {
            case: 'a funnel finishing in the data warehouse falls back to the fired mode',
            metric: funnelMetric([
                event('checkout_started'),
                { kind: NodeKind.ExperimentDataWarehouseNode, table_name: 'stripe_charges' },
            ]),
            unlinkable: [],
            expected: {
                metricSelectable: true,
                defaultMode: 'fired_all',
                labels: ['Finished funnel', "Didn't finish funnel"],
                disabledReasons: [FUNNEL_DATA_WAREHOUSE_COMPLETION_REASON, FUNNEL_DATA_WAREHOUSE_COMPLETION_REASON],
            },
        },
        {
            case: 'a mean metric names the event a session has to have fired',
            metric: meanMetric(event('purchase')),
            unlinkable: [],
            expected: {
                metricSelectable: true,
                defaultMode: 'fired_all',
                labels: ['Fired purchase', "Didn't fire purchase"],
                disabledReasons: [null, null],
            },
        },
        {
            // An action matches several events and names none of them, so naming its source would
            // promise an event the recordings filter never matches on.
            case: 'a mean metric on an action keeps the generic label',
            metric: meanMetric({ kind: NodeKind.ActionsNode, id: 12, name: 'Signed up' }),
            unlinkable: [],
            expected: {
                metricSelectable: true,
                defaultMode: 'fired_all',
                labels: ['Fired metric events', "Didn't fire metric events"],
                disabledReasons: [null, null],
            },
        },
        {
            // Naming the numerator alone would be wrong: a metric counting two events resolves as
            // the fired_any bucket, so a session matches on either one.
            case: 'a ratio metric names both of its events',
            metric: ratioMetric(event('revenue'), event('$pageview')),
            unlinkable: [],
            expected: {
                metricSelectable: true,
                defaultMode: 'fired_all',
                labels: ['Fired revenue or $pageview', "Didn't fire revenue or $pageview"],
                disabledReasons: [null, null],
            },
        },
        {
            case: 'a ratio metric on one event names it once',
            metric: ratioMetric(event('purchase'), event('purchase')),
            unlinkable: [],
            expected: {
                metricSelectable: true,
                defaultMode: 'fired_all',
                labels: ['Fired purchase', "Didn't fire purchase"],
                disabledReasons: [null, null],
            },
        },
        {
            case: 'a metric whose only event is captured server-side carries no metric',
            metric: meanMetric(event('purchase')),
            unlinkable: ['purchase'],
            expected: {
                metricSelectable: false,
                defaultMode: null,
                labels: ['Fired purchase', "Didn't fire purchase"],
                disabledReasons: [METRIC_UNLINKABLE_REASON, METRIC_UNLINKABLE_REASON],
            },
        },
        {
            case: 'a retention metric carries no metric',
            metric: {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.RETENTION,
                uuid: 'metric-retention',
                start_event: event('$pageview'),
                completion_event: event('$pageview'),
            } as unknown as ExperimentMetric,
            unlinkable: [],
            expected: {
                metricSelectable: false,
                defaultMode: null,
                labels: ['Fired metric events', "Didn't fire metric events"],
                disabledReasons: [RETENTION_UNLINKABLE_REASON, RETENTION_UNLINKABLE_REASON],
            },
        },
        {
            case: 'a data-warehouse-only metric carries no metric',
            metric: meanMetric({ kind: NodeKind.ExperimentDataWarehouseNode, table_name: 'stripe_charges' }),
            unlinkable: [],
            expected: {
                metricSelectable: false,
                defaultMode: null,
                labels: ['Fired metric events', "Didn't fire metric events"],
                disabledReasons: [DATA_WAREHOUSE_UNLINKABLE_REASON, DATA_WAREHOUSE_UNLINKABLE_REASON],
            },
        },
        {
            // The tab selects a metric by uuid, so a link to one without a uuid would land on a
            // list the metric filter never reaches.
            case: 'a metric without a uuid carries no metric',
            metric: { ...meanMetric(event('purchase')), uuid: undefined } as ExperimentMetric,
            unlinkable: [],
            expected: {
                metricSelectable: false,
                defaultMode: null,
                labels: ['Fired purchase', "Didn't fire purchase"],
                disabledReasons: [METRIC_WITHOUT_UUID_REASON, METRIC_WITHOUT_UUID_REASON],
            },
        },
    ])('$case', ({ metric, unlinkable, expected }) => {
        // The default mode decides which population one click opens, and the label is what promises
        // it. A wrong pairing sends the viewer to the opposite set of people without saying so.
        const modes = getMetricRecordingModes(metric, new Set(unlinkable))

        expect({
            metricSelectable: modes.metricSelectable,
            defaultMode: modes.defaultMode,
            labels: modes.menuItems.map((item) => item.label),
            disabledReasons: modes.menuItems.map((item) => item.disabledReason),
        }).toEqual(expected)
    })

    it('keeps everything enabled while the linkability check has not answered', () => {
        // The check resolves after the results table renders. Disabling until it lands would flash
        // a disabled menu on every visit.
        const modes = getMetricRecordingModes(meanMetric(event('purchase')), new Set())

        expect(modes.metricSelectable).toBe(true)
        expect(modes.menuItems.map((item) => item.disabledReason)).toEqual([null, null])
    })
})
