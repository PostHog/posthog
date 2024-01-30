import './AccountPopover.scss'

import { IconCheckCircle, IconFeatures, IconGear, IconLive, IconPlusSmall, IconServer } from '@posthog/icons'
import { LemonButtonPropsBase } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconBill, IconLogout } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { ThemeSwitcher } from 'scenes/settings/user/ThemeSwitcher'

import { featurePreviewsLogic } from '~/layout/FeaturePreviews/featurePreviewsLogic'
import {
    AccessLevelIndicator,
    NewOrganizationButton,
    OtherOrganizationButton,
} from '~/layout/navigation/OrganizationSwitcher'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import { organizationLogic } from '../../../scenes/organizationLogic'
import { preflightLogic } from '../../../scenes/PreflightCheck/preflightLogic'
import { urls } from '../../../scenes/urls'
import { userLogic } from '../../../scenes/userLogic'
import { OrganizationBasicType, SidePanelTab } from '../../../types'
import { navigationLogic } from '../navigationLogic'

function AccountPopoverSection({
    title,
    className,
    children,
}: {
    title?: string | JSX.Element
    className?: string
    children: any
}): JSX.Element {
    return (
        <div className={clsx('AccountPopover__section', className)}>
            {title && <h5 className="flex items-center">{title}</h5>}
            {children}
        </div>
    )
}

function AccountInfo(): JSX.Element {
    const { user } = useValues(userLogic)
    const { closeAccountPopover } = useActions(navigationLogic)

    return (
        <div className="AccountInfo">
            <LemonButton
                to={urls.settings('user')}
                onClick={closeAccountPopover}
                data-attr="top-menu-item-me"
                fullWidth
                tooltip="Account settings"
                tooltipPlacement="left"
                sideIcon={<IconGear />}
            >
                <ProfilePicture user={user} size="xl" />
                <div className="AccountInfo__identification AccountPopover__main-info font-sans font-normal">
                    <div className="font-semibold mb-1">{user?.first_name}</div>
                    <div className="supplement" title={user?.email}>
                        {user?.email}
                    </div>
                </div>
            </LemonButton>
        </div>
    )
}

function CurrentOrganization({ organization }: { organization: OrganizationBasicType }): JSX.Element {
    const { closeAccountPopover } = useActions(navigationLogic)

    return (
        <Tooltip title="Organization settings" placement="left">
            <LemonButton
                data-attr="top-menu-item-org-settings"
                icon={<Lettermark name={organization.name} />}
                sideIcon={<IconGear />}
                fullWidth
                to={urls.settings('organization')}
                onClick={closeAccountPopover}
            >
                <div className="grow">
                    <span className="font-medium">{organization.name}</span>
                    <AccessLevelIndicator organization={organization} />
                </div>
            </LemonButton>
        </Tooltip>
    )
}

export function InviteMembersButton({
    center = false,
    type = 'tertiary',
}: {
    center?: boolean
    type?: LemonButtonPropsBase['type']
}): JSX.Element {
    const { closeAccountPopover } = useActions(navigationLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)

    return (
        <LemonButton
            icon={<IconPlusSmall />}
            onClick={() => {
                closeAccountPopover()
                showInviteModal()
                reportInviteMembersButtonClicked()
            }}
            center={center}
            type={type}
            fullWidth
            data-attr="top-menu-invite-team-members"
        >
            Invite members
        </LemonButton>
    )
}

function InstanceSettings(): JSX.Element | null {
    const { closeAccountPopover } = useActions(navigationLogic)
    const { user } = useValues(userLogic)

    if (!user?.is_staff) {
        return null
    }

    return (
        <LemonButton
            icon={<IconServer />}
            onClick={closeAccountPopover}
            fullWidth
            to={urls.instanceStatus()}
            sideAction={{
                tooltip: 'Async migrations',
                tooltipPlacement: 'right',
                icon: <IconCheckCircle />,
                to: urls.asyncMigrations(),
                onClick: closeAccountPopover,
            }}
            data-attr="top-menu-instance-panel"
        >
            Instance panel
        </LemonButton>
    )
}

function FeaturePreviewsButton(): JSX.Element {
    const { closeAccountPopover } = useActions(navigationLogic)
    const { showFeaturePreviewsModal } = useActions(featurePreviewsLogic)

    return (
        <LemonButton
            onClick={() => {
                closeAccountPopover()
                showFeaturePreviewsModal()
            }}
            icon={<IconFeatures />}
            fullWidth
        >
            Feature previews
        </LemonButton>
    )
}

function SignOutButton(): JSX.Element {
    const { logout } = useActions(userLogic)

    return (
        <LemonButton onClick={logout} icon={<IconLogout />} fullWidth data-attr="top-menu-item-logout">
            Sign out
        </LemonButton>
    )
}

export function AccountPopoverOverlay(): JSX.Element {
    const { user, otherOrganizations } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { closeAccountPopover } = useActions(navigationLogic)
    const { billing } = useValues(billingLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    return (
        <>
            <AccountPopoverSection title="Signed in as">
                <AccountInfo />
            </AccountPopoverSection>
            <AccountPopoverSection title="Current organization">
                {currentOrganization && <CurrentOrganization organization={currentOrganization} />}
                {preflight?.cloud || !!billing ? (
                    <LemonButton
                        onClick={closeAccountPopover}
                        to={urls.organizationBilling()}
                        icon={<IconBill />}
                        fullWidth
                        data-attr="top-menu-item-billing"
                    >
                        Billing
                    </LemonButton>
                ) : null}
                <InviteMembersButton />
            </AccountPopoverSection>
            {(otherOrganizations.length > 0 || preflight?.can_create_org) && (
                <AccountPopoverSection title="Other organizations">
                    {otherOrganizations.map((otherOrganization, i) => (
                        <OtherOrganizationButton
                            key={otherOrganization.id}
                            organization={otherOrganization}
                            index={i + 2}
                        />
                    ))}
                    {preflight?.can_create_org && <NewOrganizationButton />}
                </AccountPopoverSection>
            )}
            <AccountPopoverSection>
                <ThemeSwitcher fullWidth type="tertiary" />
                <LemonButton
                    to="https://posthog.com/changelog"
                    onClick={(e) => {
                        closeAccountPopover()
                        if (!mobileLayout) {
                            e.preventDefault()
                            openSidePanel(SidePanelTab.Docs, '/changelog')
                        }
                    }}
                    icon={<IconLive />}
                    fullWidth
                    data-attr="whats-new-button"
                    targetBlank
                >
                    What's new?
                </LemonButton>
                <FeaturePreviewsButton />
                {user?.is_staff && <InstanceSettings />}
            </AccountPopoverSection>
            <AccountPopoverSection>
                <SignOutButton />
            </AccountPopoverSection>
        </>
    )
}
