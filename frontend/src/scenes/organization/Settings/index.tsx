import { actionToUrl, urlToAction } from 'kea-router'
import { useState } from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { Invites } from './Invites'
import { Members } from './Members'
import { organizationLogic } from '../../organizationLogic'
import { kea, useActions, useValues, path, actions, reducers } from 'kea'
import { DangerZone } from './DangerZone'
import { RestrictedArea, RestrictedComponentProps } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { useAnchor } from 'lib/hooks/useAnchor'
import { VerifiedDomains } from './VerifiedDomains/VerifiedDomains'
import { LemonButton, LemonDivider, LemonInput, LemonSwitch } from '@posthog/lemon-ui'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { AvailableFeature } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import type { organizationSettingsTabsLogicType } from './indexType'
import { PermissionsGrid } from './Permissions/PermissionsGrid'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

export const scene: SceneExport = {
    component: OrganizationSettings,
    logic: organizationLogic,
}

export enum OrganizationSettingsTabs {
    GENERAL = 'general',
    ROLE_BASED_ACCESS = 'role_based_access',
}

function DisplayName({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const [name, setName] = useState(currentOrganization?.name || '')

    return (
        <div className="max-w-160">
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

const organizationSettingsTabsLogic = kea<organizationSettingsTabsLogicType>([
    path(['scenes', 'organization', 'Settings', 'index']),
    actions({
        setTab: (tab: OrganizationSettingsTabs) => ({ tab }),
    }),
    reducers({
        tab: [
            OrganizationSettingsTabs.GENERAL as OrganizationSettingsTabs,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
    actionToUrl(() => ({
        setTab: ({ tab }) => `${urls.organizationSettings()}?tab=${tab}`,
    })),
    urlToAction(({ values, actions }) => ({
        [urls.organizationSettings()]: (_, searchParams) => {
            if (searchParams['tab'] && values.tab !== searchParams['tab']) {
                actions.setTab(searchParams['tab'])
            }
        },
    })),
])

export function OrganizationSettings(): JSX.Element {
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    useAnchor(location.hash)
    const { tab } = useValues(organizationSettingsTabsLogic)
    const { setTab } = useActions(organizationSettingsTabsLogic)

    const tabs = [
        {
            key: OrganizationSettingsTabs.GENERAL,
            label: 'General',
            content: (
                <div className="border rounded p-6">
                    <RestrictedArea Component={DisplayName} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                    <LemonDivider className="my-6" />
                    <Invites />
                    <LemonDivider className="my-6" />
                    {user && <Members user={user} />}
                    <LemonDivider className="my-6" />
                    <RestrictedArea
                        Component={VerifiedDomains}
                        minimumAccessLevel={OrganizationMembershipLevel.Admin}
                    />
                    <LemonDivider className="my-6" />
                    <RestrictedArea
                        Component={EmailPreferences}
                        minimumAccessLevel={OrganizationMembershipLevel.Admin}
                    />
                    <LemonDivider className="my-6" />
                    <RestrictedArea Component={DangerZone} minimumAccessLevel={OrganizationMembershipLevel.Owner} />
                </div>
            ),
        },
    ]

    if (featureFlags[FEATURE_FLAGS.ROLE_BASED_ACCESS]) {
        tabs.push({
            key: OrganizationSettingsTabs.ROLE_BASED_ACCESS,
            label: 'Role-based access',
            content: (
                <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
                    <RestrictedArea
                        Component={PermissionsGrid}
                        minimumAccessLevel={OrganizationMembershipLevel.Admin}
                    />
                </PayGateMini>
            ),
        })
    }

    return (
        <>
            <PageHeader
                title="Organization Settings"
                caption="View and manage your organization here. Build an even better product together."
            />

            <LemonTabs activeKey={tab} onChange={setTab} tabs={tabs} />
        </>
    )
}
