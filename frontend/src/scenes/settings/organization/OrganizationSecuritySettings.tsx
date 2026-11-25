import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { organizationLogic } from 'scenes/organizationLogic'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

const PUBLIC_SHARING_HELP = 'When disabled, sharing links and public dashboards will be blocked for this organization.'
const MEMBER_LIST_HELP =
    "When disabled, only admins and owners can see all organization members. Members will only see themselves in the members list, and only people with project access in a project's access control."

export function OrganizationSecuritySettings(): JSX.Element | null {
    const { currentOrganization } = useValues(organizationLogic)
    const { user } = useValues(userLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const adminRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!user) {
        return null
    }

    const handlePublicSharingChange = (allow_publicly_shared_resources: boolean): void => {
        if (!allow_publicly_shared_resources) {
            LemonDialog.open({
                title: 'Disable public sharing?',
                description: (
                    <div>
                        <p>
                            Disabling public sharing will immediately break all existing sharing links and public
                            dashboards for this organization.
                        </p>
                        <p>
                            Users will no longer be able to access any shared resources until this setting is
                            re-enabled.
                        </p>
                    </div>
                ),
                primaryButton: {
                    children: 'Disable sharing',
                    status: 'danger',
                    onClick: () => updateOrganization({ allow_publicly_shared_resources }),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        } else {
            updateOrganization({ allow_publicly_shared_resources })
        }
    }

    const handleMemberListChange = (members_can_see_org_members: boolean): void => {
        updateOrganization({ members_can_see_org_members })
    }

    if (todayRailNav) {
        return (
            <PayGateMini
                feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}
                featureDetail="organization-sharing-and-member-visibility"
            >
                <div className="flex flex-col gap-2">
                    <QuillSettingSwitch
                        label="Enable publicly shared resources"
                        help={PUBLIC_SHARING_HELP}
                        dataAttr="org-allow-publicly-shared-resources-toggle"
                        checked={!!currentOrganization?.allow_publicly_shared_resources}
                        onCheckedChange={handlePublicSharingChange}
                        disabledReason={adminRestrictionReason}
                    />
                    <QuillSettingSwitch
                        label="Members can see the full member list"
                        help={MEMBER_LIST_HELP}
                        dataAttr="org-members-can-see-org-members-toggle"
                        checked={currentOrganization?.members_can_see_org_members ?? true}
                        onCheckedChange={handleMemberListChange}
                        disabledReason={adminRestrictionReason}
                    />
                </div>
            </PayGateMini>
        )
    }

    return (
        <>
            <PayGateMini
                feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}
                featureDetail="organization-sharing-and-member-visibility"
            >
                <LemonSwitch
                    label={
                        <span>
                            Enable publicly shared resources{' '}
                            <Tooltip title={PUBLIC_SHARING_HELP}>
                                <IconInfo className="mr-1" />
                            </Tooltip>
                        </span>
                    }
                    bordered
                    data-attr="org-allow-publicly-shared-resources-toggle"
                    checked={!!currentOrganization?.allow_publicly_shared_resources}
                    onChange={handlePublicSharingChange}
                    disabledReason={adminRestrictionReason}
                />
                <LemonSwitch
                    label={
                        <span>
                            Members can see the full member list{' '}
                            <Tooltip title={MEMBER_LIST_HELP}>
                                <IconInfo className="mr-1" />
                            </Tooltip>
                        </span>
                    }
                    bordered
                    className="mt-2"
                    data-attr="org-members-can-see-org-members-toggle"
                    checked={currentOrganization?.members_can_see_org_members ?? true}
                    onChange={handleMemberListChange}
                    disabledReason={adminRestrictionReason}
                />
            </PayGateMini>
        </>
    )
}
