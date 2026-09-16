import { getSelectorMatchChangeActionIds } from 'scenes/insights/selectorMatchChange'

import { NodeKind } from '~/queries/schema/schema-general'

describe('getSelectorMatchChangeActionIds', () => {
    const actionSeries = (id: number): Record<string, any> => ({ kind: NodeKind.ActionsNode, id })
    const eventSeries = { kind: NodeKind.EventsNode, event: '$pageview' }

    it.each<[string, (Record<string, any> | null | undefined)[] | null | undefined, number[]]>([
        ['one action', [actionSeries(1)], [1]],
        ['an action alongside an event', [eventSeries, actionSeries(1)], [1]],
        ['the same action twice', [actionSeries(1), actionSeries(1)], [1]],
        ['several actions', [actionSeries(4), actionSeries(2)], [2, 4]],
        ['events only', [eventSeries], []],
        ['no series', null, []],
        ['an undefined series', undefined, []],
    ])('resolves %s', (_name, series, expected) => {
        expect(getSelectorMatchChangeActionIds(series)).toEqual(expected)
    })
})
