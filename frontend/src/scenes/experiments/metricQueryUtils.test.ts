import type { ActionsNode, EventsNode, ExperimentMetric } from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'

import { getFilter } from './metricQueryUtils'

describe('getFilter', () => {
    it('returns the correct filter for an event', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: 'total',
                math_property: undefined,
                math_hogql: undefined,
                properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'event' }],
            } as EventsNode,
        }
        const filter = getFilter(metric)
        expect(filter).toEqual({
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    math: 'total',
                    math_property: undefined,
                    math_hogql: undefined,
                    properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'event' }],
                    kind: NodeKind.EventsNode,
                },
            ],
            actions: [],
            data_warehouse: [],
        })
    })
    it('returns the correct filter for an action', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ActionsNode,
                id: 8,
                name: 'jan-16-running payment action',
                math: 'total',
                math_property: undefined,
                math_hogql: undefined,
                properties: [{ key: '$lib', type: 'event', value: ['python'], operator: 'exact' }],
            } as ActionsNode,
        }
        const filter = getFilter(metric)
        expect(filter).toEqual({
            events: [],
            actions: [
                {
                    id: 8,
                    name: 'jan-16-running payment action',
                    type: 'actions',
                    math: 'total',
                    math_property: undefined,
                    math_hogql: undefined,
                    properties: [{ key: '$lib', type: 'event', value: ['python'], operator: 'exact' }],
                    kind: NodeKind.ActionsNode,
                },
            ],
            data_warehouse: [],
        })
    })
})
