import { getSelectorMatchChangeActionIds } from 'scenes/insights/selectorMatchChange'

import { NodeKind } from '~/queries/schema/schema-general'

describe('getSelectorMatchChangeActionIds', () => {
    const actionSeries = (id: number): Record<string, any> => ({ kind: NodeKind.ActionsNode, id })
    const eventSeries = { kind: NodeKind.EventsNode, event: '$pageview' }
    const retentionEntity = (id: number | string): Record<string, any> => ({ type: 'actions', id })

    it.each<[string, Record<string, any> | null | undefined, number[]]>([
        ['one action', { series: [actionSeries(1)] }, [1]],
        ['an action alongside an event', { series: [eventSeries, actionSeries(1)] }, [1]],
        ['the same action twice', { series: [actionSeries(1), actionSeries(1)] }, [1]],
        ['several actions', { series: [actionSeries(4), actionSeries(2)] }, [2, 4]],
        [
            'both retention entities',
            { retentionFilter: { targetEntity: retentionEntity(3), returningEntity: retentionEntity(5) } },
            [3, 5],
        ],
        ['a retention entity with a string id', { retentionFilter: { targetEntity: retentionEntity('7') } }, [7]],
        [
            'a retention entity that is an event',
            { retentionFilter: { targetEntity: { type: 'events', id: '$pageview' } } },
            [],
        ],
        [
            'the funnel a paths query walks',
            { funnelPathsFilter: { funnelSource: { series: [actionSeries(9), eventSeries] } } },
            [9],
        ],
        ['events only', { series: [eventSeries] }, []],
        ['no series', { series: null }, []],
        ['an empty query source', {}, []],
        ['an undefined query source', undefined, []],
    ])('resolves %s', (_name, querySource, expected) => {
        expect(getSelectorMatchChangeActionIds(querySource)).toEqual(expected)
    })
})
