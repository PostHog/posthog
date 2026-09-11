import { hasSelectorMatchChange } from 'scenes/insights/selectorMatchChange'

import { NodeKind } from '~/queries/schema/schema-general'
import { ActionType } from '~/types'

describe('hasSelectorMatchChange', () => {
    const action = (id: number, changedSteps?: number[]): ActionType =>
        ({ id, name: `action ${id}`, selector_match_changed_steps: changedSteps }) as ActionType

    const actionsById = {
        1: action(1, [0]),
        2: action(2, []),
        3: action(3),
    }

    const actionSeries = (id: number): Record<string, any> => ({ kind: NodeKind.ActionsNode, id })
    const eventSeries = { kind: NodeKind.EventsNode, event: '$pageview' }

    it.each<[string, (Record<string, any> | null | undefined)[] | null | undefined, boolean]>([
        ['an action with a changed step', [actionSeries(1)], true],
        ['a changed action alongside an event', [eventSeries, actionSeries(1)], true],
        ['an action with no changed steps', [actionSeries(2)], false],
        ['an action the API reported nothing for', [actionSeries(3)], false],
        ['an action that has not loaded yet', [actionSeries(99)], false],
        ['events only', [eventSeries], false],
        ['no series', null, false],
        ['an undefined series', undefined, false],
    ])('is %s -> %s', (_name, series, expected) => {
        expect(hasSelectorMatchChange(series, actionsById)).toBe(expected)
    })
})
