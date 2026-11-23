import { Field as KeaField } from 'kea-forms'
import { useId } from 'react'

import { Field, FieldLabel, Text, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { QuillScopeTargetCombobox } from './QuillScopeTargetCombobox'
import type { AccessType, OrganizationOption, TeamOption } from './types'
import { createTeamOption } from './utils'

const ACCESS_TYPE_OPTIONS: { label: string; value: AccessType }[] = [
    { label: 'All access', value: 'all' },
    { label: 'Organizations', value: 'organizations' },
    { label: 'Projects', value: 'teams' },
]

export function QuillUserDefinedAccessSelector({
    accessType,
    organizations,
    teams,
}: {
    accessType?: AccessType
    organizations: OrganizationOption[]
    teams?: TeamOption[]
}): JSX.Element {
    const idPrefix = useId()

    return (
        <div className="flex flex-col gap-2">
            <KeaField name="access_type" noStyle>
                {({ value, onChange }) => (
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Text size="xs" weight="medium" render={<span />} className="m-0">
                            Organization & project access
                        </Text>
                        <ToggleGroup
                            variant="outline"
                            aria-label="Organization & project access"
                            value={value ? [value] : []}
                            onValueChange={(next: string[]) => {
                                if (next[0]) {
                                    onChange(next[0])
                                }
                            }}
                        >
                            {ACCESS_TYPE_OPTIONS.map((option) => (
                                <ToggleGroupItem key={option.value} value={option.value}>
                                    {option.label}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                    </div>
                )}
            </KeaField>

            {accessType === 'all' ? (
                <Text size="xs" render={<p className="m-0" />}>
                    This will allow access to all organizations and projects you're in.
                </Text>
            ) : accessType === 'organizations' ? (
                <KeaField name="scoped_organizations" noStyle>
                    {({ value, onChange }) => (
                        <Field>
                            <FieldLabel htmlFor={`${idPrefix}-organizations`}>
                                This will only allow access to selected organizations and all projects within them.
                            </FieldLabel>
                            <QuillScopeTargetCombobox
                                id={`${idPrefix}-organizations`}
                                options={organizations.map((org) => ({
                                    value: org.id,
                                    label: org.name,
                                    description: `ID: ${org.id}`,
                                }))}
                                value={value ?? []}
                                onChange={onChange}
                                placeholder="Select organizations..."
                                emptyText="No matching organizations"
                                dataAttr="organizations"
                            />
                        </Field>
                    )}
                </KeaField>
            ) : accessType === 'teams' ? (
                <KeaField name="scoped_teams" noStyle>
                    {({ value, onChange }) => (
                        <Field>
                            <FieldLabel htmlFor={`${idPrefix}-teams`}>
                                This will only allow access to selected projects.
                            </FieldLabel>
                            <QuillScopeTargetCombobox
                                id={`${idPrefix}-teams`}
                                options={(teams || []).map((team) => {
                                    const option = createTeamOption(team, organizations)

                                    return {
                                        value: option.key,
                                        label: option.label,
                                        description: `Token: ${team.api_token}`,
                                    }
                                })}
                                value={(value ?? []).map((x: number) => String(x))}
                                onChange={(val: string[]) => onChange(val.map((x) => parseInt(x)))}
                                placeholder="Select projects..."
                                emptyText="No matching projects"
                                dataAttr="teams"
                            />
                        </Field>
                    )}
                </KeaField>
            ) : null}
        </div>
    )
}
