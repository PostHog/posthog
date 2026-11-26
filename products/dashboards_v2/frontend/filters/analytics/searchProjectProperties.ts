import { ApiConfig } from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { propertyDefinitionsList } from '~/generated/core/api'
import { PropertyDefinitionsListType } from '~/generated/core/api.schemas'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import type { FeaturedProperty } from '../property/propertyFilterSpec'

const LIMIT = 30

/** The project's event and person properties whose name matches, with an event property first when both share a name. */
export async function searchProjectProperties(search: string, signal: AbortSignal): Promise<FeaturedProperty[]> {
    const projectId = String(ApiConfig.getCurrentProjectId())
    const [events, persons] = await Promise.all(
        [PropertyDefinitionsListType.Event, PropertyDefinitionsListType.Person].map((type) =>
            propertyDefinitionsList(projectId, { type, search, limit: LIMIT, exclude_hidden: true }, { signal })
        )
    )
    const seen = new Set<string>()
    const pick = (
        names: string[],
        source: FeaturedProperty['source'],
        group: TaxonomicFilterGroupType
    ): FeaturedProperty[] =>
        names.flatMap((key) => {
            if (seen.has(key)) {
                return []
            }
            seen.add(key)
            return [{ key, source, label: getCoreFilterDefinition(key, group)?.label ?? key }]
        })
    return [
        ...pick(
            events.results.map((property) => property.name),
            'event',
            TaxonomicFilterGroupType.EventProperties
        ),
        ...pick(
            persons.results.map((property) => property.name),
            'person',
            TaxonomicFilterGroupType.PersonProperties
        ),
    ]
}
