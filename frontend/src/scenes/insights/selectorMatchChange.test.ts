import { SelectorMatchChange, getSelectorMatchChanges } from 'scenes/insights/selectorMatchChange'

import { NodeKind } from '~/queries/schema/schema-general'
import { ActionType } from '~/types'

describe('getSelectorMatchChanges', () => {
    const action = (id: number, changedSteps?: number[], selectors?: (string | undefined)[]): ActionType =>
        ({
            id,
            name: `action ${id}`,
            steps: selectors?.map((selector) => ({ selector })),
            selector_match_changed_steps: changedSteps,
        }) as ActionType

    const actionsById = {
        1: action(1, [0], ['div .btn:nth-child(2)', '.sibling']),
        2: action(2, [], ['.fine']),
        3: action(3),
        4: action(4, [1], ['.first', '.second']),
        5: action(5, [0], [undefined]),
        6: { ...action(6, [0], ['.unnamed']), name: null } as ActionType,
    }

    const actionSeries = (id: number): Record<string, any> => ({ kind: NodeKind.ActionsNode, id })
    const eventSeries = { kind: NodeKind.EventsNode, event: '$pageview' }

    it.each<[string, (Record<string, any> | null | undefined)[] | null | undefined, SelectorMatchChange[]]>([
        [
            'an action with a changed step',
            [actionSeries(1)],
            [{ actionId: 1, actionName: 'action 1', selectors: ['div .btn:nth-child(2)'] }],
        ],
        [
            'a changed action alongside an event',
            [eventSeries, actionSeries(1)],
            [{ actionId: 1, actionName: 'action 1', selectors: ['div .btn:nth-child(2)'] }],
        ],
        [
            'the same action twice',
            [actionSeries(1), actionSeries(1)],
            [{ actionId: 1, actionName: 'action 1', selectors: ['div .btn:nth-child(2)'] }],
        ],
        [
            'a changed step that is not the first',
            [actionSeries(4)],
            [{ actionId: 4, actionName: 'action 4', selectors: ['.second'] }],
        ],
        [
            'a step that has lost its selector',
            [actionSeries(5)],
            [{ actionId: 5, actionName: 'action 5', selectors: [] }],
        ],
        [
            'an unnamed action',
            [actionSeries(6)],
            [{ actionId: 6, actionName: 'Untitled action', selectors: ['.unnamed'] }],
        ],
        ['an action with no changed steps', [actionSeries(2)], []],
        ['an action the API reported nothing for', [actionSeries(3)], []],
        ['an action that has not loaded yet', [actionSeries(99)], []],
        ['events only', [eventSeries], []],
        ['no series', null, []],
        ['an undefined series', undefined, []],
    ])('resolves %s', (_name, series, expected) => {
        expect(getSelectorMatchChanges(series, actionsById)).toEqual(expected)
    })
})
