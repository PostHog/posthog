import { LemonInputSelect, LemonLabel, Tooltip } from '@posthog/lemon-ui'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import type { OrganizationBasicType, TeamBasicType } from '~/types'

type Props = {
    organizations: Pick<OrganizationBasicType, 'id' | 'name'>[]
    teams?: Pick<TeamBasicType, 'id' | 'name' | 'organization' | 'api_token'>[]
    accessType?: 'all' | 'organizations' | 'teams'
}

const ScopeAccessSelector = ({ accessType, organizations, teams }: Props): JSX.Element => {
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
                        <LemonInputSelect
                            mode="multiple"
                            data-attr="organizations"
                            options={
                                organizations.map((org) => ({
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
                                })) ?? []
                            }
                            loading={organizations === undefined}
                            placeholder="Select organizations..."
                        />
                    </LemonField>
                </>
            ) : accessType === 'teams' ? (
                <>
                    <p className="mb-2">This will only allow access to selected projects.</p>
                    <LemonField name="scoped_teams">
                        {({ value, onChange }) => (
                            <LemonInputSelect
                                mode="multiple"
                                data-attr="teams"
                                value={value.map((x: number) => String(x))}
                                onChange={(val: string[]) => onChange(val.map((x) => parseInt(x)))}
                                options={
                                    teams?.map((team) => ({
                                        key: `${team.id}`,
                                        label: team.name,
                                        labelComponent: (
                                            <Tooltip
                                                title={
                                                    <div>
                                                        <div className="font-semibold">{team.name}</div>
                                                        <div className="text-xs whitespace-nowrap">
                                                            Token: {team.api_token}
                                                        </div>
                                                        <div className="text-xs whitespace-nowrap">
                                                            Organization ID: {team.organization}
                                                        </div>
                                                    </div>
                                                }
                                            >
                                                {organizations.length > 1 ? (
                                                    <span>
                                                        <span>
                                                            {
                                                                organizations.find(
                                                                    (org) => org.id === team.organization
                                                                )?.name
                                                            }
                                                        </span>
                                                        <span className="text-secondary mx-1">/</span>
                                                        <span className="flex-1 font-semibold">{team.name}</span>
                                                    </span>
                                                ) : (
                                                    <span>{team.name}</span>
                                                )}
                                            </Tooltip>
                                        ),
                                    })) ?? []
                                }
                                loading={teams === undefined}
                                placeholder="Select projects..."
                            />
                        )}
                    </LemonField>
                </>
            ) : null}
        </div>
    )
}

export default ScopeAccessSelector
