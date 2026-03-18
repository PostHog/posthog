import { LemonLabel } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import { OrganizationSelector } from './OrganizationSelector'
import { TeamSelector } from './TeamSelector'
import type { AccessType, OrganizationOption, TeamOption } from './types'

type UserDefinedAccessSelectorProps = {
    accessType?: AccessType
    organizations: OrganizationOption[]
    teams?: TeamOption[]
}

export const UserDefinedAccessSelector = ({
    accessType,
    organizations,
    teams,
}: UserDefinedAccessSelectorProps): JSX.Element => {
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
