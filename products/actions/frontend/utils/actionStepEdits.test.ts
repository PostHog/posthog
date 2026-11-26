import { ActionStepType, AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    actionStepFilters,
    actionStepScreenNames,
    withActionStepFilters,
    withActionStepScreenName,
    withActionStepType,
} from './actionStepEdits'

const BROWSER_FILTER: AnyPropertyFilter = {
    key: '$browser',
    value: 'Chrome',
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}
const SCREEN_NAME_FILTER: AnyPropertyFilter = {
    key: '$screen_name',
    value: 'HomeScreen',
    operator: PropertyOperator.IContains,
    type: PropertyFilterType.Event,
}

describe('actionStepEdits', () => {
    it('clears the URL fields when a pageview step becomes a screen step', () => {
        const pageview: ActionStepType = { event: '$pageview', url: 'posthog.com/pricing', url_matching: 'contains' }

        expect(withActionStepType(pageview, '$screen')).toEqual({ event: '$screen', url: null, url_matching: null })
    })

    it('keeps the screen name filter out of the generic filters and puts it back on change', () => {
        const step: ActionStepType = { event: '$screen', properties: [SCREEN_NAME_FILTER, BROWSER_FILTER] }

        expect(actionStepFilters(step)).toEqual([BROWSER_FILTER])
        expect(withActionStepFilters(step, []).properties).toEqual([SCREEN_NAME_FILTER])
    })

    it.each([
        ['an empty name', '', [BROWSER_FILTER]],
        ['an empty list', [], [BROWSER_FILTER]],
    ])('removes the screen name filter for %s', (_, value, expected) => {
        const step: ActionStepType = { event: '$screen', properties: [SCREEN_NAME_FILTER, BROWSER_FILTER] }

        expect(withActionStepScreenName(step, value, PropertyOperator.Exact).properties).toEqual(expected)
    })

    it('replaces the screen name filter and reads it back', () => {
        const step: ActionStepType = { event: '$screen', properties: [SCREEN_NAME_FILTER, BROWSER_FILTER] }

        const updated = withActionStepScreenName(step, ['HomeScreen', 'Settings'], PropertyOperator.Exact)

        expect(actionStepScreenNames(updated)).toEqual({
            screenNames: ['HomeScreen', 'Settings'],
            operator: PropertyOperator.Exact,
        })
        expect(updated.properties).toHaveLength(2)
    })
})
