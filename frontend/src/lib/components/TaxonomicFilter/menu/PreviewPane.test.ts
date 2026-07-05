import { urls } from 'scenes/urls'

import { PropertyDefinition } from '~/types'

import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../types'
import { resolveViewUrl } from './PreviewPane'
import { MenuFilterEntry } from './types'

// resolveViewUrl is the rebuild's separate implementation of the legacy
// definitionPopoverLogic.viewFullDetailUrl selector — no test enforces parity
// between the two. Per-type id recovery lives in (and is tested via)
// resolvePropertyDefinitionId; these cases only guard that the rebuild delegates
// to it and hides the link when nothing resolves (the /properties/undefined regression).
describe('resolveViewUrl', () => {
    const entry = (type: TaxonomicFilterGroupType, item: Partial<PropertyDefinition>): MenuFilterEntry =>
        ({ item, group: { type } as TaxonomicFilterGroup, name: String(item.name ?? '') }) as MenuFilterEntry

    it('builds the property URL from the recovered id for a name-only item', () => {
        const getPropertyDefinition = (name: string): PropertyDefinition | null =>
            name === '$current_url' ? ({ name, id: 'event-url-id' } as PropertyDefinition) : null

        const url = resolveViewUrl(
            entry(TaxonomicFilterGroupType.EventProperties, { name: '$current_url' }),
            getPropertyDefinition
        )

        expect(url).toBe(urls.propertyDefinition('event-url-id'))
    })

    it('stays undefined when a name-only property cannot be resolved', () => {
        const url = resolveViewUrl(entry(TaxonomicFilterGroupType.EventProperties, { name: 'never-saved' }), () => null)
        expect(url).toBeUndefined()
    })
})
