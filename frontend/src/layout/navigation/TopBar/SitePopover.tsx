import { IconChevronDown, IconFeatures, IconLive } from '@posthog/icons'
import { LemonButtonPropsBase } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import {
    IconBill,
    IconCheckmark,
    IconCorporate,
    IconExclamation,
    IconLogout,
    IconOffline,
    IconPlus,
    IconSettings,
    IconUpdate,
} from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
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

import { organizationLogic } from '../../../scenes/organizationLogic'
import { preflightLogic } from '../../../scenes/PreflightCheck/preflightLogic'
import { urls } from '../../../scenes/urls'
import { userLogic } from '../../../scenes/userLogic'
import { OrganizationBasicType } from '../../../types'
import { navigationLogic } from '../navigationLogic'

function SitePopoverSection({
    title,
    className,
    children,
}: {
    title?: string | JSX.Element
    className?: string
    children: any
}): JSX.Element {
    return (
        <div className={clsx('SitePopover__section', className)}>
            {title && <h5 className="flex items-center">{title}</h5>}
            {children}
        </div>
    )
}

function AccountInfo(): JSX.Element {
    const { user } = useValues(userLogic)
    const { closeSitePopover } = useActions(navigationLogic)

    return (
        <div className="AccountInfo">
            <LemonButton
                to={urls.settings('user')}
                onClick={closeSitePopover}
                data-attr="top-menu-item-me"
                status="stealth"
                fullWidth
                tooltip="Account settings"
                tooltipPlacement="left"
                sideIcon={<IconSettings className="text-2xl" />}
            >
                <ProfilePicture user={user} size="xl" />
                <div className="AccountInfo__identification SitePopover__main-info font-sans font-normal">
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
    const { closeSitePopover } = useActions(navigationLogic)

    return (
        <Tooltip title="Organization settings" placement="left">
            <LemonButton
                data-attr="top-menu-item-org-settings"
                icon={<Lettermark name={organization.name} />}
                sideIcon={<IconSettings />}
                status="stealth"
                fullWidth
                to={urls.settings('organization')}
                onClick={closeSitePopover}
            >
                <div className="SitePopover__main-info SitePopover__organization">
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
    const { closeSitePopover } = useActions(navigationLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            onClick={() => {
                closeSitePopover()
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

function SystemStatus(): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)
    const { systemStatusHealthy } = useValues(navigationLogic)

    return (
        <LemonRow
            status={systemStatusHealthy ? 'success' : 'danger'}
            icon={systemStatusHealthy ? <IconCheckmark /> : <IconOffline />}
            fullWidth
        >
            <>
                <div className="SitePopover__main-info">
                    {systemStatusHealthy ? 'All systems operational' : 'Potential system issue'}
                </div>
                <Link
                    to={urls.instanceStatus()}
                    onClick={closeSitePopover}
                    className="SitePopover__side-link"
                    data-attr="system-status-badge"
                >
                    Instance status
                </Link>
            </>
        </LemonRow>
    )
}

function AsyncMigrations(): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)
    const { asyncMigrationsOk } = useValues(navigationLogic)

    return (
        <LemonRow
            status={asyncMigrationsOk ? 'success' : 'warning'}
            icon={asyncMigrationsOk ? <IconCheckmark /> : <IconUpdate />}
            fullWidth
        >
            <>
                <div className="SitePopover__main-info">
                    {asyncMigrationsOk ? 'Async migrations up-to-date' : 'Pending async migrations'}
                </div>
                <Link
                    to={urls.asyncMigrations()}
                    onClick={closeSitePopover}
                    className="SitePopover__side-link"
                    data-attr="async-migrations-status-badge"
                >
                    Manage
                </Link>
            </>
        </LemonRow>
    )
}

function InstanceSettings(): JSX.Element | null {
    const { closeSitePopover } = useActions(navigationLogic)
    const { user } = useValues(userLogic)

    if (!user?.is_staff) {
        return null
    }

    return (
        <Link to={urls.instanceSettings()}>
            <LemonButton icon={<IconCorporate className="text-link" />} onClick={closeSitePopover} fullWidth>
                Instance settings
            </LemonButton>
        </Link>
    )
}

function FeaturePreviewsButton(): JSX.Element {
    const { closeSitePopover } = useActions(navigationLogic)
    const { showFeaturePreviewsModal } = useActions(featurePreviewsLogic)

    return (
        <LemonButton
            onClick={() => {
                closeSitePopover()
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
        <LemonButton onClick={logout} icon={<IconLogout />} status="stealth" fullWidth data-attr="top-menu-item-logout">
            Sign out
        </LemonButton>
    )
}

export function SitePopoverOverlay(): JSX.Element {
    const { user, otherOrganizations } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { closeSitePopover } = useActions(navigationLogic)
    const { billing } = useValues(billingLogic)

    return (
        <>
            <SitePopoverSection title="Signed in as">
                <AccountInfo />
            </SitePopoverSection>
            <SitePopoverSection title="Current organization">
                {currentOrganization && <CurrentOrganization organization={currentOrganization} />}
                {preflight?.cloud || !!billing ? (
                    <LemonButton
                        onClick={closeSitePopover}
                        to={urls.organizationBilling()}
                        icon={<IconBill />}
                        fullWidth
                        data-attr="top-menu-item-billing"
                    >
                        Billing
                    </LemonButton>
                ) : null}
                <InviteMembersButton />
            </SitePopoverSection>
            {(otherOrganizations.length > 0 || preflight?.can_create_org) && (
                <SitePopoverSection title="Other organizations">
                    {otherOrganizations.map((otherOrganization, i) => (
                        <OtherOrganizationButton
                            key={otherOrganization.id}
                            organization={otherOrganization}
                            index={i + 2}
                        />
                    ))}
                    {preflight?.can_create_org && <NewOrganizationButton />}
                </SitePopoverSection>
            )}
            {(!(preflight?.cloud || preflight?.demo) || user?.is_staff) && (
                <SitePopoverSection title="PostHog instance" className="font-title-3000">
                    <SystemStatus />
                    <AsyncMigrations />
                    <InstanceSettings />
                </SitePopoverSection>
            )}
            <SitePopoverSection>
                <FlaggedFeature flag={FEATURE_FLAGS.POSTHOG_3000} match="test">
                    <ThemeSwitcher fullWidth type="tertiary" />
                </FlaggedFeature>
                <LemonButton
                    onClick={closeSitePopover}
                    to={'https://posthog.com/changelog'}
                    icon={<IconLive />}
                    fullWidth
                    data-attr="whats-new-button"
                    targetBlank
                >
                    What's new?
                </LemonButton>
                <FeaturePreviewsButton />
            </SitePopoverSection>
            <SitePopoverSection>
                <SignOutButton />
            </SitePopoverSection>
        </>
    )
}

export function SitePopover(): JSX.Element {
    const { user } = useValues(userLogic)
    const { isSitePopoverOpen, systemStatusHealthy } = useValues(navigationLogic)
    const { toggleSitePopover, closeSitePopover } = useActions(navigationLogic)

    return (
        <Popover
            visible={isSitePopoverOpen}
            className="SitePopover"
            onClickOutside={closeSitePopover}
            overlay={<SitePopoverOverlay />}
        >
            <div className="SitePopover__crumb" onClick={toggleSitePopover} data-attr="top-menu-toggle">
                <div className="SitePopover__profile-picture" title="Potential system issue">
                    <ProfilePicture user={user} size="md" />
                    {!systemStatusHealthy && <IconExclamation className="SitePopover__danger" />}
                </div>
                <IconChevronDown />
            </div>
        </Popover>
    )
}
