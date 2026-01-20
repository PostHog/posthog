import { useEffect, useMemo, useState } from 'react'

import { IconBuilding, IconCheck, IconChevronRight, IconFolder } from '@posthog/icons'
import { LemonCheckbox, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'

import type { OrganizationBasicType, TeamBasicType } from '~/types'

export type OrganizationOption = Pick<OrganizationBasicType, 'id' | 'name'>
export type TeamOption = Pick<TeamBasicType, 'id' | 'name' | 'organization' | 'api_token'>

export type AccessType = 'all' | 'organizations' | 'teams'
export type RequiredAccessLevel = 'organization' | 'team' | null

export type OAuthScopeSelectorProps = {
    organizations: OrganizationOption[]
    teams?: TeamOption[]
    accessType?: AccessType
    requiredAccessLevel?: RequiredAccessLevel
    autoSelectFirst?: boolean
}

export function OAuthScopeSelector({
    organizations,
    teams = [],
    accessType = 'all',
    requiredAccessLevel,
    autoSelectFirst = false,
}: OAuthScopeSelectorProps): JSX.Element {
    if (requiredAccessLevel === 'organization') {
        return <RequiredOrganizationSelector organizations={organizations} autoSelectFirst={autoSelectFirst} />
    }

    if (requiredAccessLevel === 'team') {
        return <RequiredTeamSelector teams={teams} organizations={organizations} autoSelectFirst={autoSelectFirst} />
    }

    return <UserDefinedScopeSelector accessType={accessType} organizations={organizations} teams={teams} />
}

// For when app requires organization-level access
function RequiredOrganizationSelector({
    organizations,
    autoSelectFirst = false,
}: {
    organizations: OrganizationOption[]
    autoSelectFirst?: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <IconBuilding className="text-muted text-lg" />
                <span className="font-semibold">Select organization</span>
            </div>
            <p className="text-sm text-muted mb-1">This application requires access to a specific organization.</p>
            <LemonField name="scoped_organizations">
                {({ value, onChange }) => {
                    const arrayValue = Array.isArray(value) ? value : []

                    useEffect(() => {
                        if (autoSelectFirst && arrayValue.length === 0 && organizations.length > 0) {
                            onChange([organizations[0].id])
                        }
                    }, [autoSelectFirst, organizations, arrayValue.length, onChange])

                    return (
                        <div className="flex flex-col gap-2 max-h-[300px] overflow-y-auto border rounded p-2">
                            {organizations.map((org) => (
                                <OrganizationRow
                                    key={org.id}
                                    org={org}
                                    selected={arrayValue.includes(org.id)}
                                    onSelect={() => onChange([org.id])}
                                    mode="single"
                                />
                            ))}
                        </div>
                    )
                }}
            </LemonField>
        </div>
    )
}

// For when app requires team-level access
function RequiredTeamSelector({
    teams,
    organizations,
    autoSelectFirst = false,
}: {
    teams: TeamOption[]
    organizations: OrganizationOption[]
    autoSelectFirst?: boolean
}): JSX.Element {
    const [searchQuery, setSearchQuery] = useState('')

    const teamsByOrg = useMemo(() => {
        const grouped: Record<string, TeamOption[]> = {}
        for (const team of teams) {
            if (!grouped[team.organization]) {
                grouped[team.organization] = []
            }
            grouped[team.organization].push(team)
        }
        return grouped
    }, [teams])

    const filteredTeamsByOrg = useMemo(() => {
        if (!searchQuery) {
            return teamsByOrg
        }
        const query = searchQuery.toLowerCase()
        const filtered: Record<string, TeamOption[]> = {}
        for (const [orgId, orgTeams] of Object.entries(teamsByOrg)) {
            const org = organizations.find((o) => o.id === orgId)
            const orgMatches = org?.name.toLowerCase().includes(query)
            const matchingTeams = orgTeams.filter((t) => t.name.toLowerCase().includes(query) || orgMatches)
            if (matchingTeams.length > 0) {
                filtered[orgId] = matchingTeams
            }
        }
        return filtered
    }, [teamsByOrg, searchQuery, organizations])

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <IconFolder className="text-muted text-lg" />
                <span className="font-semibold">Select project</span>
            </div>
            <p className="text-sm text-muted mb-1">This application requires access to a specific project.</p>
            <LemonField name="scoped_teams">
                {({ value, onChange }) => {
                    const arrayValue = Array.isArray(value) ? value.map(Number) : []

                    useEffect(() => {
                        if (autoSelectFirst && arrayValue.length === 0 && teams.length > 0) {
                            onChange([teams[0].id])
                        }
                    }, [autoSelectFirst, teams, arrayValue.length, onChange])

                    return (
                        <>
                            {teams.length > 5 && (
                                <LemonInput
                                    type="search"
                                    placeholder="Search projects..."
                                    value={searchQuery}
                                    onChange={setSearchQuery}
                                    className="mb-2"
                                />
                            )}
                            <div className="flex flex-col gap-1 max-h-[300px] overflow-y-auto border rounded p-2">
                                {Object.entries(filteredTeamsByOrg).map(([orgId, orgTeams]) => {
                                    const org = organizations.find((o) => o.id === orgId)
                                    return (
                                        <OrgProjectGroup
                                            key={orgId}
                                            org={org}
                                            teams={orgTeams}
                                            selectedTeamIds={arrayValue}
                                            onSelectTeam={(teamId) => onChange([teamId])}
                                            mode="single"
                                            defaultExpanded={organizations.length === 1}
                                        />
                                    )
                                })}
                            </div>
                        </>
                    )
                }}
            </LemonField>
        </div>
    )
}

// For user-defined access (no required level)
function UserDefinedScopeSelector({
    accessType = 'all',
    organizations,
    teams = [],
}: {
    accessType?: AccessType
    organizations: OrganizationOption[]
    teams?: TeamOption[]
}): JSX.Element {
    const [searchQuery, setSearchQuery] = useState('')

    const teamsByOrg = useMemo(() => {
        const grouped: Record<string, TeamOption[]> = {}
        for (const team of teams) {
            if (!grouped[team.organization]) {
                grouped[team.organization] = []
            }
            grouped[team.organization].push(team)
        }
        return grouped
    }, [teams])

    return (
        <div className="flex flex-col gap-4">
            <LemonField name="access_type">
                {({ value, onChange }) => (
                    <div className="flex flex-col gap-3">
                        <div className="flex items-center justify-between">
                            <div>
                                <div className="font-semibold">Access scope</div>
                                <div className="text-sm text-muted">
                                    Choose which organizations and projects this app can access
                                </div>
                            </div>
                        </div>

                        <div className="flex flex-col gap-2 border rounded p-3 bg-bg-light">
                            <AccessOption
                                selected={value === 'all'}
                                onSelect={() => onChange('all')}
                                icon={<IconCheck className="text-success" />}
                                title="All organizations and projects"
                                description="Full access to all current and future organizations and projects"
                            />
                            <AccessOption
                                selected={value === 'organizations'}
                                onSelect={() => onChange('organizations')}
                                icon={<IconBuilding className="text-muted" />}
                                title="Selected organizations"
                                description="Access to specific organizations and all their projects"
                            />
                            <AccessOption
                                selected={value === 'teams'}
                                onSelect={() => onChange('teams')}
                                icon={<IconFolder className="text-muted" />}
                                title="Selected projects"
                                description="Access to specific projects only"
                            />
                        </div>
                    </div>
                )}
            </LemonField>

            {accessType === 'organizations' && (
                <LemonField name="scoped_organizations">
                    {({ value, onChange }) => {
                        const arrayValue = Array.isArray(value) ? value : []
                        return (
                            <div className="flex flex-col gap-2">
                                <div className="text-sm text-muted">
                                    Select the organizations this app should have access to:
                                </div>
                                <div className="flex flex-col gap-2 max-h-[250px] overflow-y-auto border rounded p-2">
                                    {organizations.map((org) => (
                                        <OrganizationRow
                                            key={org.id}
                                            org={org}
                                            selected={arrayValue.includes(org.id)}
                                            onSelect={() => {
                                                if (arrayValue.includes(org.id)) {
                                                    onChange(arrayValue.filter((id: string) => id !== org.id))
                                                } else {
                                                    onChange([...arrayValue, org.id])
                                                }
                                            }}
                                            mode="multiple"
                                        />
                                    ))}
                                </div>
                                {arrayValue.length === 0 && (
                                    <div className="text-sm text-warning">Select at least one organization</div>
                                )}
                            </div>
                        )
                    }}
                </LemonField>
            )}

            {accessType === 'teams' && (
                <LemonField name="scoped_teams">
                    {({ value, onChange }) => {
                        const arrayValue = Array.isArray(value) ? value.map(Number) : []
                        return (
                            <div className="flex flex-col gap-2">
                                <div className="text-sm text-muted">
                                    Select the projects this app should have access to:
                                </div>
                                {teams.length > 5 && (
                                    <LemonInput
                                        type="search"
                                        placeholder="Search projects..."
                                        value={searchQuery}
                                        onChange={setSearchQuery}
                                    />
                                )}
                                <div className="flex flex-col gap-1 max-h-[250px] overflow-y-auto border rounded p-2">
                                    {Object.entries(teamsByOrg).map(([orgId, orgTeams]) => {
                                        const org = organizations.find((o) => o.id === orgId)
                                        const filteredTeams = searchQuery
                                            ? orgTeams.filter(
                                                  (t) =>
                                                      t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                                                      org?.name.toLowerCase().includes(searchQuery.toLowerCase())
                                              )
                                            : orgTeams
                                        if (filteredTeams.length === 0) {
                                            return null
                                        }
                                        return (
                                            <OrgProjectGroup
                                                key={orgId}
                                                org={org}
                                                teams={filteredTeams}
                                                selectedTeamIds={arrayValue}
                                                onSelectTeam={(teamId) => {
                                                    if (arrayValue.includes(teamId)) {
                                                        onChange(arrayValue.filter((id) => id !== teamId))
                                                    } else {
                                                        onChange([...arrayValue, teamId])
                                                    }
                                                }}
                                                onSelectAllTeams={(teamIds, selected) => {
                                                    if (selected) {
                                                        onChange([...new Set([...arrayValue, ...teamIds])])
                                                    } else {
                                                        onChange(arrayValue.filter((id) => !teamIds.includes(id)))
                                                    }
                                                }}
                                                mode="multiple"
                                                defaultExpanded={organizations.length === 1}
                                            />
                                        )
                                    })}
                                </div>
                                {arrayValue.length === 0 && (
                                    <div className="text-sm text-warning">Select at least one project</div>
                                )}
                            </div>
                        )
                    }}
                </LemonField>
            )}

            {accessType === 'all' && (
                <div className="text-sm text-muted bg-bg-light border rounded p-3">
                    <strong>Note:</strong> This will grant access to all organizations and projects you currently have
                    access to, as well as any you may be added to in the future.
                </div>
            )}
        </div>
    )
}

// Helper components

function AccessOption({
    selected,
    onSelect,
    icon,
    title,
    description,
}: {
    selected: boolean
    onSelect: () => void
    icon: React.ReactNode
    title: string
    description: string
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onSelect}
            className={`flex items-start gap-3 p-3 rounded border transition-colors text-left ${
                selected ? 'border-primary bg-primary/5' : 'border-transparent hover:bg-fill-button-tertiary-hover'
            }`}
        >
            <div
                className={`flex items-center justify-center w-5 h-5 rounded-full border-2 mt-0.5 ${
                    selected ? 'border-primary bg-primary' : 'border-border'
                }`}
            >
                {selected && <IconCheck className="text-bg-light text-xs" />}
            </div>
            <div className="flex-1">
                <div className="flex items-center gap-2">
                    {icon}
                    <span className="font-medium">{title}</span>
                </div>
                <div className="text-sm text-muted mt-0.5">{description}</div>
            </div>
        </button>
    )
}

function OrganizationRow({
    org,
    selected,
    onSelect,
    mode,
}: {
    org: OrganizationOption
    selected: boolean
    onSelect: () => void
    mode: 'single' | 'multiple'
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onSelect}
            className={`flex items-center gap-3 p-2 rounded transition-colors text-left ${
                selected ? 'bg-primary/10' : 'hover:bg-fill-button-tertiary-hover'
            }`}
        >
            {mode === 'multiple' ? (
                <LemonCheckbox checked={selected} className="pointer-events-none" />
            ) : (
                <div
                    className={`flex items-center justify-center w-4 h-4 rounded-full border-2 ${
                        selected ? 'border-primary bg-primary' : 'border-border'
                    }`}
                >
                    {selected && <IconCheck className="text-bg-light text-[10px]" />}
                </div>
            )}
            <UploadedLogo name={org.name} entityId={org.id} outlinedLettermark size="small" />
            <span className="font-medium truncate flex-1">{org.name}</span>
        </button>
    )
}

function OrgProjectGroup({
    org,
    teams,
    selectedTeamIds,
    onSelectTeam,
    onSelectAllTeams,
    mode,
    defaultExpanded = false,
}: {
    org: OrganizationOption | undefined
    teams: TeamOption[]
    selectedTeamIds: number[]
    onSelectTeam: (teamId: number) => void
    onSelectAllTeams?: (teamIds: number[], selected: boolean) => void
    mode: 'single' | 'multiple'
    defaultExpanded?: boolean
}): JSX.Element {
    const [expanded, setExpanded] = useState(defaultExpanded)
    const allSelected = teams.every((t) => selectedTeamIds.includes(t.id))
    const someSelected = teams.some((t) => selectedTeamIds.includes(t.id))

    return (
        <div className="flex flex-col">
            <button
                type="button"
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-2 p-2 rounded hover:bg-fill-button-tertiary-hover text-left"
            >
                <IconChevronRight className={`text-muted transition-transform ${expanded ? 'rotate-90' : ''}`} />
                <UploadedLogo name={org?.name || 'Unknown'} entityId={org?.id} outlinedLettermark size="small" />
                <span className="font-medium truncate flex-1">{org?.name || 'Unknown Organization'}</span>
                {mode === 'multiple' && onSelectAllTeams && (
                    <Tooltip title={allSelected ? 'Deselect all' : 'Select all'}>
                        <div
                            onClick={(e) => {
                                e.stopPropagation()
                                onSelectAllTeams(
                                    teams.map((t) => t.id),
                                    !allSelected
                                )
                            }}
                        >
                            <LemonCheckbox
                                checked={allSelected ? true : someSelected ? 'indeterminate' : false}
                                className="pointer-events-none"
                            />
                        </div>
                    </Tooltip>
                )}
                <span className="text-xs text-muted">{teams.length}</span>
            </button>
            {expanded && (
                <div className="flex flex-col gap-1 ml-6 pl-2 border-l">
                    {teams.map((team) => (
                        <button
                            key={team.id}
                            type="button"
                            onClick={() => onSelectTeam(team.id)}
                            className={`flex items-center gap-2 p-2 rounded transition-colors text-left ${
                                selectedTeamIds.includes(team.id)
                                    ? 'bg-primary/10'
                                    : 'hover:bg-fill-button-tertiary-hover'
                            }`}
                        >
                            {mode === 'multiple' ? (
                                <LemonCheckbox
                                    checked={selectedTeamIds.includes(team.id)}
                                    className="pointer-events-none"
                                />
                            ) : (
                                <div
                                    className={`flex items-center justify-center w-4 h-4 rounded-full border-2 ${
                                        selectedTeamIds.includes(team.id)
                                            ? 'border-primary bg-primary'
                                            : 'border-border'
                                    }`}
                                >
                                    {selectedTeamIds.includes(team.id) && (
                                        <IconCheck className="text-bg-light text-[10px]" />
                                    )}
                                </div>
                            )}
                            <IconFolder className="text-muted text-sm" />
                            <span className="truncate flex-1">{team.name}</span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    )
}

export default OAuthScopeSelector
