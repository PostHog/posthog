import { useEffect } from 'react'

import { LemonLabel } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { OrganizationSelector } from './OrganizationSelector'
import type { OrganizationOption } from './types'

type RequiredOrganizationAccessSelectorProps = {
    organizations: OrganizationOption[]
    autoSelectFirst?: boolean
}

export const RequiredOrganizationAccessSelector = ({
    organizations,
    autoSelectFirst = false,
}: RequiredOrganizationAccessSelectorProps): JSX.Element => {
    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>Select organization</LemonLabel>
            <p className="text-sm text-muted mb-2">This application requires access to a specific organization.</p>
            <LemonField name="scoped_organizations">
                {({ value, onChange }) => {
                    const arrayValue = Array.isArray(value) ? value : []

                    useEffect(() => {
                        if (autoSelectFirst && arrayValue.length === 0 && organizations.length > 0) {
                            onChange([organizations[0].id])
                        }
                    }, [autoSelectFirst, organizations, arrayValue.length, onChange])

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
