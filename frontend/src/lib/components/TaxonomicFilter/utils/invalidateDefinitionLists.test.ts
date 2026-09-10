import { renderHook, waitFor } from '@testing-library/react'

import { __clearTaxonomicResourceCache, useTaxonomicResource } from '../hooks/useTaxonomicResource'
import { invalidateDefinitionLists, isDefinitionTaxonomicListKey } from './invalidateDefinitionLists'

describe('invalidateDefinitionLists', () => {
    beforeEach(() => {
        __clearTaxonomicResourceCache()
    })

    it.each([
        [['taxonomic-list', 'event_properties', 'api/projects/1/property_definitions?type=event'], true],
        [['taxonomic-list-search', 'events', 'api/projects/1/event_definitions', null], true],
        [['taxonomic-list', 'session_properties', 'api/environments/1/sessions/property_definitions'], true],
        [['taxonomic-list', 'cohorts', 'api/projects/1/cohorts/'], false],
        [['something-else', 'events', 'api/projects/1/event_definitions'], false],
    ])('classifies %j as a definition list: %s', (key, expected) => {
        expect(isDefinitionTaxonomicListKey(key)).toBe(expected)
    })

    it('refetches cached definition lists and leaves other lists cached', async () => {
        const definitions = jest.fn().mockResolvedValueOnce('d1').mockResolvedValueOnce('d2')
        const cohorts = jest.fn().mockResolvedValueOnce('c1')
        const d = renderHook(() =>
            useTaxonomicResource(['taxonomic-list', 'events', 'api/projects/1/event_definitions'], definitions)
        )
        const c = renderHook(() =>
            useTaxonomicResource(['taxonomic-list', 'cohorts', 'api/projects/1/cohorts/'], cohorts)
        )
        await waitFor(() => expect(d.result.current.data).toBe('d1'))
        await waitFor(() => expect(c.result.current.data).toBe('c1'))

        invalidateDefinitionLists()
        d.rerender()
        c.rerender()

        await waitFor(() => expect(d.result.current.data).toBe('d2'))
        expect(cohorts).toHaveBeenCalledTimes(1)
    })
})
