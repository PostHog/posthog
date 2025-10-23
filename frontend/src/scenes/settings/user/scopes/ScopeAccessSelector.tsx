import { useEffect } from 'react'

import { LemonInputSelect, LemonInputSelectOption, LemonLabel, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import type { OrganizationBasicType, TeamBasicType } from '~/types'

type Props = {
    organizations: Pick<OrganizationBasicType, 'id' | 'name'>[]
    teams?: Pick<TeamBasicType, 'id' | 'name' | 'organization' | 'api_token'>[]
    accessType?: 'all' | 'organizations' | 'teams'
    requiredAccessLevel?: 'organization' | 'team' | null
    autoSelectFirst?: boolean
}

const createOrganizationOption = (
    org: Pick<OrganizationBasicType, 'id' | 'name'>
): LemonInputSelectOption<string> => ({
    key: `${org.id}`,
    label: org.name,
    labelComponent: (
        <Tooltip
            title={
                <div>
                    <div className="font-semibold">{org.name}</div>
                    <div className="text-xs whitespace-nowrap">ID: {org.id}</div>
                </div>
            }
        >
            <span className="flex-1 font-semibold">{org.name}</span>
        </Tooltip>
    ),
})

const createTeamOption = (
    team: Pick<TeamBasicType, 'id' | 'name' | 'organization' | 'api_token'>,
    organizations: Pick<OrganizationBasicType, 'id' | 'name'>[]
): LemonInputSelectOption<string> => {
    const orgName = organizations.find((org) => org.id === team.organization)?.name
    const displayLabel = organizations.length > 1 && orgName ? `${orgName} / ${team.name}` : team.name

    return {
        key: `${team.id}`,
        label: displayLabel,
        labelComponent: (
            <Tooltip
                title={
                    <div>
                        <div className="font-semibold">{team.name}</div>
                        <div className="text-xs whitespace-nowrap">Token: {team.api_token}</div>
                        <div className="text-xs whitespace-nowrap">Organization ID: {team.organization}</div>
                    </div>
                }
            >
                {organizations.length > 1 ? (
                    <span>
                        <span>{orgName}</span>
                        <span className="text-secondary mx-1">/</span>
                        <span className="flex-1 font-semibold">{team.name}</span>
                    </span>
                ) : (
                    <span>{team.name}</span>
                )}
            </Tooltip>
        ),
    }
}

const OrganizationSelector = ({
    organizations,
    mode,
    value,
    onChange,
}: {
    organizations: Pick<OrganizationBasicType, 'id' | 'name'>[]
    mode: 'single' | 'multiple'
    value?: string[]
    onChange?: (val: string[]) => void
}): JSX.Element => (
    <LemonInputSelect
        mode={mode}
        data-attr="organizations"
        value={value}
        onChange={onChange}
        options={organizations.map((org) => createOrganizationOption(org)) ?? []}
        loading={organizations === undefined}
        placeholder={mode === 'single' ? 'Select an organization...' : 'Select organizations...'}
    />
)

const TeamSelector = ({
    teams,
    organizations,
    mode,
    value,
    onChange,
}: {
    teams: Pick<TeamBasicType, 'id' | 'name' | 'organization' | 'api_token'>[]
    organizations: Pick<OrganizationBasicType, 'id' | 'name'>[]
    mode: 'single' | 'multiple'
    value?: string[]
    onChange?: (val: string[]) => void
}): JSX.Element => (
    <LemonInputSelect
        mode={mode}
        data-attr="teams"
        value={value}
        onChange={onChange}
        options={(teams || []).map((team) => createTeamOption(team, organizations))}
        loading={teams === undefined}
        placeholder={mode === 'single' ? 'Select a project...' : 'Select projects...'}
    />
)

const ScopeAccessSelector = ({
    accessType,
    organizations,
    teams,
    requiredAccessLevel,
    autoSelectFirst = false,
}: Props): JSX.Element => {
    if (requiredAccessLevel === 'organization') {
        return (
            <div className="flex flex-col gap-2">
                <LemonLabel>Select organization</LemonLabel>
                <p className="text-sm text-muted mb-2">
                    This application requires access to a specific organization.
                </p>
                <LemonField name="scoped_organizations">
                    {({ value, onChange }) => {
                        const arrayValue = Array.isArray(value) ? value : []

                        useEffect(() => {
                            if (autoSelectFirst && arrayValue.length === 0 && organizations.length > 0) {
                                onChange([organizations[0].id])
                            }
                        }, [autoSelectFirst, organizations])

                        return (
                            <OrganizationSelector
                                organizations={organizations}
                                mode="single"
                                value={arrayValue.length > 0 ? [arrayValue[0]] : []}
                                onChange={(val: string[]) => onChange(val.length > 0 ? [val[0]] : [])}
                            />
                        )
                    }}
                </LemonField>
            </div>
        )
    }

    if (requiredAccessLevel === 'team') {
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
                        }, [autoSelectFirst, teams])

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

    return (
        <div className="flex flex-col gap-2">
            <LemonField name="access_type" className="mt-4 mb-2">
                {({ value, onChange }) => (
                    <div className="flex flex-col gap-2 md:flex-row items-start md:items-center justify-between">
                        <LemonLabel>Organization & project access</LemonLabel>
                        <LemonSegmentedButton
                            onChange={onChange}
                            value={value}
                            options={[
                                { label: 'All access', value: 'all' },
                                {
                                    label: 'Organizations',
                                    value: 'organizations',
                                },
                                {
                                    label: 'Projects',
                                    value: 'teams',
                                },
                            ]}
                            size="small"
                        />
                    </div>
                )}
            </LemonField>

            {accessType === 'all' ? (
                <p className="mb-0">This will allow access to all organizations and projects you're in.</p>
            ) : accessType === 'organizations' ? (
                <>
                    <p className="mb-2">
                        This will only allow access to selected organizations and all projects within them.
                    </p>

                    <LemonField name="scoped_organizations">
                        <OrganizationSelector organizations={organizations} mode="multiple" />
                    </LemonField>
                </>
            ) : accessType === 'teams' ? (
                <>
                    <p className="mb-2">This will only allow access to selected projects.</p>
                    <LemonField name="scoped_teams">
                        {({ value, onChange }) => (
                            <TeamSelector
                                teams={teams || []}
                                organizations={organizations}
                                mode="multiple"
                                value={value.map((x: number) => String(x))}
                                onChange={(val: string[]) => onChange(val.map((x) => parseInt(x)))}
                            />
                        )}
                    </LemonField>
                </>
            ) : null}
        </div>
    )
}

export default ScopeAccessSelector
