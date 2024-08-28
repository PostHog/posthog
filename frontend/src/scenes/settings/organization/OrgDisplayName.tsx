import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useState } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationDisplayName(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const [name, setName] = useState(currentOrganization?.name || '')

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    return (
        <div className="max-w-160">
            <LemonInput
                className="mb-4"
                value={name}
                onChange={setName}
                disabled={!!restrictionReason}
                data-attr="organization-name-input-settings"
            />
            <LemonButton
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    updateOrganization({ name })
                }}
                disabledReason={
                    !name
                        ? 'You must provide a name'
                        : !currentOrganization
                        ? 'Organization not loaded'
                        : currentOrganization.name === name
                        ? 'Name unchanged'
                        : restrictionReason
                }
                loading={currentOrganizationLoading}
            >
                Rename organization
            </LemonButton>
        </div>
    )
}
