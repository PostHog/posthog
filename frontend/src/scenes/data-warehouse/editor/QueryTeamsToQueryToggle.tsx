import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { canUseCrossProjectQuerying } from 'lib/utils/teamsToQuery'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { sqlEditorLogic } from './sqlEditorLogic'

interface QueryTeamsToQueryToggleProps {
    disabledReason?: string
}

export function QueryTeamsToQueryToggle({ disabledReason }: QueryTeamsToQueryToggleProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { sourceQuery } = useValues(sqlEditorLogic)
    const { setSourceQuery, syncUrlWithQuery } = useActions(sqlEditorLogic)

    if (!canUseCrossProjectQuerying(currentTeam, currentOrganization)) {
        return null
    }

    return (
        <LemonSwitch
            bordered
            checked={sourceQuery.source.modifiers?.teamsToQuery === 'all'}
            onChange={(checked) => {
                setSourceQuery({
                    ...sourceQuery,
                    source: {
                        ...sourceQuery.source,
                        modifiers: {
                            ...sourceQuery.source.modifiers,
                            teamsToQuery: checked ? 'all' : 'self',
                        },
                    },
                })
                syncUrlWithQuery()
            }}
            disabledReason={disabledReason}
            label="Query all projects in this organization"
        />
    )
}
