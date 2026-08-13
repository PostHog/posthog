import { combineUrl } from 'kea-router'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { matchingActorsUrl } from './matchingActorsUrl'

describe('matchingActorsUrl', () => {
    const personProperty: AnyPropertyFilter = {
        key: 'email',
        value: 'is_set',
        operator: PropertyOperator.IsSet,
        type: PropertyFilterType.Person,
    }
    const flagDependency: AnyPropertyFilter = {
        key: '123',
        value: true,
        operator: PropertyOperator.FlagEvaluatesTo,
        type: PropertyFilterType.Flag,
    }

    it('links a person-targeted condition to the persons list with the filters in the query', () => {
        const parsed = combineUrl(matchingActorsUrl([personProperty], null))
        expect(parsed.pathname).toBe('/persons')
        expect(parsed.hashParams.q.source.kind).toBe('ActorsQuery')
        expect(parsed.hashParams.q.source.properties).toEqual([personProperty])
    })

    it('links a group-targeted condition to that group type list with the filters', () => {
        const parsed = combineUrl(matchingActorsUrl([personProperty], 1))
        expect(parsed.pathname).toBe('/groups/1')
        expect(JSON.parse(parsed.searchParams.properties_1)).toEqual([personProperty])
    })

    it('strips flag-dependency filters the actor lists cannot evaluate', () => {
        const persons = combineUrl(matchingActorsUrl([personProperty, flagDependency], null))
        expect(persons.hashParams.q.source.properties).toEqual([personProperty])

        const groups = combineUrl(matchingActorsUrl([personProperty, flagDependency], 0))
        expect(JSON.parse(groups.searchParams.properties_0)).toEqual([personProperty])
    })
})
