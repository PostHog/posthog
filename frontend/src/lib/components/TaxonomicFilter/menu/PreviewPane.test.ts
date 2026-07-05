import { urls } from 'scenes/urls'

import { PropertyDefinition, PropertyDefinitionType } from '~/types'

import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../types'
import { resolveViewUrl } from './PreviewPane'
import { MenuFilterEntry } from './types'

// The rebuild's resolveViewUrl is a separate implementation of the legacy
// definitionPopoverLogic.viewFullDetailUrl selector — no test enforces parity
// between the two, so this guards the rebuild's own id-recovery for name-only
// pinned/default property items (the /properties/undefined regression).
describe('resolveViewUrl', () => {
    const entry = (type: TaxonomicFilterGroupType, item: Partial<PropertyDefinition>): MenuFilterEntry =>
        ({ item, group: { type } as TaxonomicFilterGroup, name: String(item.name ?? '') }) as MenuFilterEntry

    const definition = (name: string, id: string): PropertyDefinition => ({ name, id }) as PropertyDefinition

    it('uses the id already on the item', () => {
        const url = resolveViewUrl(
            entry(TaxonomicFilterGroupType.EventProperties, { name: '$browser', id: 'abc' }),
            () => null
        )
        expect(url).toBe(urls.propertyDefinition('abc'))
    })

    it.each([
        [TaxonomicFilterGroupType.EventProperties, '$current_url', 'event-url-id'],
        [TaxonomicFilterGroupType.PersonProperties, 'email', 'person-email-id'],
    ])('recovers a missing id for a name-only %s item', (type, name, id) => {
        const getPropertyDefinition = (n: string): PropertyDefinition | null =>
            n === name ? definition(name, id) : null

        const url = resolveViewUrl(entry(type, { name }), getPropertyDefinition)

        expect(url).toBe(urls.propertyDefinition(id))
    })

    it('passes the mapped PropertyDefinitionType through to the resolver', () => {
        const seen: PropertyDefinitionType[] = []
        const getPropertyDefinition = (_: string, defType: PropertyDefinitionType): PropertyDefinition | null => {
            seen.push(defType)
            return null
        }

        resolveViewUrl(entry(TaxonomicFilterGroupType.PersonProperties, { name: 'email' }), getPropertyDefinition)

        expect(seen).toEqual([PropertyDefinitionType.Person])
    })

    it('stays undefined when a name-only property cannot be resolved', () => {
        const url = resolveViewUrl(entry(TaxonomicFilterGroupType.EventProperties, { name: 'never-saved' }), () => null)
        expect(url).toBeUndefined()
    })
})
