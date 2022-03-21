import React, { useState } from 'react'
import { Button, Card, Input, Divider, Switch } from 'antd'
import { PageHeader } from 'lib/components/PageHeader'
import { Invites } from './Invites'
import { Members } from './Members'
import { organizationLogic } from '../../organizationLogic'
import { useActions, useValues } from 'kea'
import { DangerZone } from './DangerZone'
import { RestrictedArea, RestrictedComponentProps } from '../../../lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from '../../../lib/constants'
import { userLogic } from 'scenes/userLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { useAnchor } from 'lib/hooks/useAnchor'
import { VerifiedDomains } from './VerifiedDomains/VerifiedDomains'

export const scene: SceneExport = {
    component: OrganizationSettings,
    logic: organizationLogic,
}

function DisplayName({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const [name, setName] = useState(currentOrganization?.name || '')

    return (
        <div>
            <h2 id="name" className="subtitle">
                Display Name
            </h2>
            <Input
                value={name}
                onChange={(event) => {
                    setName(event.target.value)
                }}
                style={{ maxWidth: '40rem', marginBottom: '1rem', display: 'block' }}
                disabled={isRestricted}
            />
            <Button
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    updateOrganization({ name })
                }}
                disabled={isRestricted || !name || !currentOrganization || name === currentOrganization.name}
                loading={currentOrganizationLoading}
            >
                Rename Organization
            </Button>
        </div>
    )
}

function EmailPreferences({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    return (
        <div>
            <h2 id="notification-preferences" className="subtitle">
                Notification Preferences
            </h2>
            <div>
                <Switch
                    id="is-member-join-email-enabled-switch"
                    data-attr="is-member-join-email-enabled-switch"
                    onChange={(checked) => {
                        updateOrganization({ is_member_join_email_enabled: checked })
                    }}
                    checked={currentOrganization?.is_member_join_email_enabled}
                    loading={currentOrganizationLoading}
                    disabled={isRestricted || !currentOrganization}
                />
                <label
                    style={{
                        marginLeft: '10px',
                    }}
                    htmlFor="is-member-join-email-enabled-switch"
                >
                    Email all current members when a new member joins
                </label>
            </div>
        </div>
    )
}

export function OrganizationSettings(): JSX.Element {
    const { user } = useValues(userLogic)
    useAnchor(location.hash)

    return (
        <>
            <PageHeader
                title="Organization Settings"
                caption="View and manage your organization here. Build an even better product together."
            />
            <Card>
                <RestrictedArea Component={DisplayName} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <Divider />
                <Invites />
                <Divider />
                {user && <Members user={user} />}
                <Divider />
                <RestrictedArea Component={VerifiedDomains} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <Divider />
                <RestrictedArea Component={EmailPreferences} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <Divider />
                <RestrictedArea Component={DangerZone} minimumAccessLevel={OrganizationMembershipLevel.Owner} />
            </Card>
        </>
    )
}
