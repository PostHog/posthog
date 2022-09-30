import React, { useState } from 'react'
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
import { LemonButton, LemonDivider, LemonInput, LemonSwitch } from '@posthog/lemon-ui'
import { membersLogic } from './membersLogic'
import { LemonSelectMultiple } from 'lib/components/LemonSelectMultiple/LemonSelectMultiple'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { OrganizationMemberType } from '~/types'

export const scene: SceneExport = {
    component: OrganizationSettings,
    logic: organizationLogic,
}

function DisplayName({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const [name, setName] = useState(currentOrganization?.name || '')

    return (
        <div style={{ maxWidth: '40rem' }}>
            <h2 id="name" className="subtitle mt-0">
                Display Name
            </h2>
            <LemonInput className="mb-4" value={name} onChange={setName} disabled={isRestricted} />
            <LemonButton
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    updateOrganization({ name })
                }}
                disabled={isRestricted || !name || !currentOrganization || name === currentOrganization.name}
                loading={currentOrganizationLoading}
            >
                Rename Organization
            </LemonButton>
        </div>
    )
}

function EmailPreferences({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    return (
        <div>
            <h2 id="notification-preferences" className="subtitle">
                Notification Preferences
            </h2>
            <div>
                <LemonSwitch
                    data-attr="is-member-join-email-enabled-switch"
                    onChange={(checked) => {
                        updateOrganization({ is_member_join_email_enabled: checked })
                    }}
                    checked={!!currentOrganization?.is_member_join_email_enabled}
                    disabled={isRestricted || !currentOrganization}
                    label="Email all current members when a new member joins"
                    bordered
                />
            </div>
        </div>
    )
}

function PluginAlertPreference({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { members, membersLoading } = useValues(membersLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    return (
        <div>
            <h2 id="plugin-notification-preferences" className="subtitle">
                Sending plugin alerts
            </h2>
            <div>
                Select members of your team who should receive alerts if a plugin gets disabled. If no-one is selected,
                everyone will get these emails.
                <LemonSelectMultiple
                    mode="multiple"
                    onChange={function We(user) {
                        updateOrganization({ members_to_send_plugin_alerts: user })
                    }}
                    disabled={isRestricted}
                    loading={membersLoading}
                    options={usersLemonSelectOptions(
                        members.map((x: OrganizationMemberType) => x.user),
                        'uuid'
                    )}
                    placeholder="Pick users to notify"
                    value={currentOrganization.members_to_send_plugin_alerts}
                />
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
            <div className="border rounded p-6">
                <RestrictedArea Component={DisplayName} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <LemonDivider className="my-6" />
                <Invites />
                <LemonDivider className="my-6" />
                {user && <Members user={user} />}
                <LemonDivider className="my-6" />
                <RestrictedArea Component={VerifiedDomains} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <LemonDivider className="my-6" />
                <RestrictedArea Component={EmailPreferences} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <LemonDivider className="my-6" />
                <RestrictedArea
                    Component={PluginAlertPreference}
                    minimumAccessLevel={OrganizationMembershipLevel.Admin}
                />
                <LemonDivider className="my-6" />
                <RestrictedArea Component={DangerZone} minimumAccessLevel={OrganizationMembershipLevel.Owner} />
            </div>
        </>
    )
}
