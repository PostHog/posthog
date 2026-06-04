import { useEffect } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TopMatchItem } from 'lib/components/TaxonomicFilter/utils/redistributeTopMatches'

import { useGroupList } from '../hooks/useGroupList'
import { TaxonomicFilterGroup } from '../types'
import { useTaxonomicFilterContext } from './context'

/**
 * Headless, render-nothing collector that feeds the SuggestedFilters tab's
 * cross-tab aggregation. Mounts one invisible probe per content group while a
 * query is active; each probe runs the same `useGroupList` the tab counts
 * already run (so the fetch is shared via the resource cache) and publishes its
 * top matches into the orchestrator's registry.
 *
 * Why a child-per-group component rather than a `.map` of `useGroupList`: the
 * visible group set can change between renders, and a bare hook-in-a-loop would
 * violate the Rules of Hooks. One component instance per group (keyed by type)
 * makes each hook's lifecycle independent — the same pattern `Categories` uses.
 */
export function SuggestedTopMatchCollector(): JSX.Element | null {
    const { groups, groupTypes, metaGroupTypes, searchQuery } = useTaxonomicFilterContext()

    if (!searchQuery.trim() || !groupTypes.includes(TaxonomicFilterGroupType.SuggestedFilters)) {
        return null
    }

    const contentGroups = groups.filter((g) => !metaGroupTypes.has(g.type))
    return (
        <>
            {contentGroups.map((group) => (
                <GroupTopMatchProbe key={group.type} group={group} />
            ))}
        </>
    )
}

function GroupTopMatchProbe({ group }: { group: TaxonomicFilterGroup }): null {
    const { getGroupListInput, reportTopMatches } = useTaxonomicFilterContext()
    const list = useGroupList(getGroupListInput(group))
    const matches = list.topMatchesForQuery
    const isFetching = list.isFetching

    useEffect(() => {
        const tagged: TopMatchItem[] = matches.map((item) => ({ ...item, group: group.type }) as TopMatchItem)
        reportTopMatches(group.type, tagged, isFetching)
    }, [group.type, matches, isFetching, reportTopMatches])

    return null
}
