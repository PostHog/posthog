import { useEffect } from 'react'

import { LemonLabel } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { TeamSelector } from './TeamSelector'
import type { OrganizationOption, TeamOption } from './types'

type RequiredTeamAccessSelectorProps = {
    teams: TeamOption[]
    organizations: OrganizationOption[]
    autoSelectFirst?: boolean
}

export const RequiredTeamAccessSelector = ({
    teams,
    organizations,
    autoSelectFirst = false,
}: RequiredTeamAccessSelectorProps): JSX.Element => {
    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>Select project</LemonLabel>
            <p className="text-sm text-muted mb-2">This application requires access to a specific project.</p>
            <LemonField name="scoped_teams">
                {({ value, onChange }) => {
                    const arrayValue = Array.isArray(value) ? value : []

                    useEffect(() => {
                        if (autoSelectFirst && arrayValue.length === 0 && teams && teams.length > 0) {
                            onChange([teams[0].id])
                        }
                    }, [autoSelectFirst, teams, arrayValue.length, onChange])

                    return (
                        <TeamSelector
                            teams={teams || []}
                            organizations={organizations}
                            mode="single"
                            value={arrayValue.length > 0 ? [String(arrayValue[0])] : []}
                            onChange={(val: string[]) => onChange(val.length > 0 ? [parseInt(val[0])] : [])}
                        />
                    )
                }}
            </LemonField>
        </div>
    )
}
