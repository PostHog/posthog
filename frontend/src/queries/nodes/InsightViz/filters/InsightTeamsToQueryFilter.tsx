import { useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { canUseCrossProjectQuerying } from 'lib/utils/teamsToQuery'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryModifiers, InsightQueryNode } from '~/queries/schema/schema-general'

type InsightTeamsToQueryFilterProps = {
    query: InsightQueryNode
    setQuery: (query: InsightQueryNode) => void
    disabledReason?: string
}

export function InsightTeamsToQueryFilter({
    query,
    setQuery,
    disabledReason,
}: InsightTeamsToQueryFilterProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)

    if (!canUseCrossProjectQuerying(currentTeam, currentOrganization)) {
        return null
    }

    const modifiers: HogQLQueryModifiers = query.modifiers ?? {}

    return (
        <LemonSwitch
            checked={modifiers.teamsToQuery === 'all'}
            onChange={(checked) =>
                setQuery({
                    ...query,
                    modifiers: {
                        ...modifiers,
                        teamsToQuery: checked ? 'all' : 'self',
                    },
                })
            }
            disabledReason={disabledReason}
            label="Query all projects in this organization"
            size="small"
        />
    )
}
