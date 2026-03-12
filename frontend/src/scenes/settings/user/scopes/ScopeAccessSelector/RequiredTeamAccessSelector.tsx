import { useEffect, useMemo } from 'react'

import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import type { LemonSelectSection } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

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
    const selectOptions = useMemo(() => {
        if (organizations.length <= 1) {
            return (teams || []).map((team) => ({
                value: team.id,
                label: team.name,
            }))
        }

        const orgMap = new Map(organizations.map((org) => [org.id, org.name]))
        const grouped = new Map<string, TeamOption[]>()
        for (const team of teams || []) {
            const orgId = team.organization
            if (!grouped.has(orgId)) {
                grouped.set(orgId, [])
            }
            grouped.get(orgId)!.push(team)
        }

        const sections: LemonSelectSection<number>[] = []
        for (const [orgId, orgTeams] of grouped) {
            sections.push({
                title: orgMap.get(orgId) ?? orgId,
                options: orgTeams.map((team) => ({
                    value: team.id,
                    label: team.name,
                })),
            })
        }
        return sections
    }, [teams, organizations])

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
                        <LemonSelect<number>
                            fullWidth
                            data-attr="teams"
                            value={arrayValue.length > 0 ? arrayValue[0] : null}
                            onChange={(val) => onChange(val !== null ? [val] : [])}
                            options={selectOptions}
                            placeholder="Select a project..."
                            loading={teams === undefined}
                        />
                    )
                }}
            </LemonField>
        </div>
    )
}
