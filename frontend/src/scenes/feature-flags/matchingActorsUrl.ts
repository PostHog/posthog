import { combineUrl } from 'kea-router'

import { isFlagPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { AnyPersonScopeFilter, AnyPropertyFilter } from '~/types'

// Flag-dependency filters (type: 'flag') aren't property filters the persons/groups lists can
// evaluate, so drop them before linking, matching how the backend blast radius skips them.
function toActorFilters(properties: AnyPropertyFilter[] | undefined): AnyPropertyFilter[] {
    return (properties ?? []).filter((property) => !isFlagPropertyFilter(property))
}

/**
 * Links to the list of actors matching a release condition set's properties: the groups list for a
 * group-targeted condition, otherwise the persons list.
 *
 * The param names belong to the consuming scenes and have to stay in sync with them:
 * `personsSceneLogic` reads `q` from the hash, `groupsListLogic` reads `properties_<index>` from the
 * query. Renaming either one leaves this file compiling and silently produces an unfiltered list.
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
            // Without an explicit select the backend returns its own `person` column, and the global
            // product column renderers claim that key and render "Unknown" for an actors query.
            select: defaultDataTableColumns(NodeKind.ActorsQuery),
            // A person-targeted condition (resolvedGroupTypeIndex null) only carries person and
            // cohort filters, which are person-scoped; the group-targeted case takes the branch above.
            properties: actorFilters as AnyPersonScopeFilter[],
        },
        full: true,
    }
    return combineUrl(urls.persons(), {}, { q: query }).url
}
