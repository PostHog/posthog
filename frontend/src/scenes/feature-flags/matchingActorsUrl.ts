import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { AnyPersonScopeFilter, AnyPropertyFilter, PropertyFilterType } from '~/types'

// Flag-dependency filters (type: 'flag') aren't property filters the persons/groups lists can
// evaluate, so drop them before linking, matching how the backend blast radius skips them.
function toActorFilters(properties: AnyPropertyFilter[] | undefined): AnyPropertyFilter[] {
    return (properties ?? []).filter((property) => property.type !== PropertyFilterType.Flag)
}

/**
 * Builds a link to the list of actors matching a release condition set's properties: the groups
 * list for a group-targeted condition, otherwise the persons list. Reuses each scene's own URL
 * round-trip (`q` in the hash for persons, `properties_<index>` in the query for groups).
 */
export function matchingActorsUrl(
    properties: AnyPropertyFilter[] | undefined,
    resolvedGroupTypeIndex: number | null
): string {
    const actorFilters = toActorFilters(properties)

    if (resolvedGroupTypeIndex != null) {
        return combineUrl(urls.groups(resolvedGroupTypeIndex), {
            [`properties_${resolvedGroupTypeIndex}`]: JSON.stringify(actorFilters),
        }).url
    }

    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ActorsQuery,
            // A person-targeted condition (resolvedGroupTypeIndex null) only carries person and
            // cohort filters, which are person-scoped; the group-targeted case takes the branch above.
            properties: actorFilters as AnyPersonScopeFilter[],
        },
        full: true,
    }
    return combineUrl(urls.persons(), {}, { q: query }).url
}
