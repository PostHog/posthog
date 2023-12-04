import { IconDay, IconFeatures, IconLaptop, IconLive, IconNight } from '@posthog/icons'
import { LemonButtonPropsBase, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import {
    IconArrowDropDown,
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
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'

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

function SitePopoverSection({ title, children }: { title?: string | JSX.Element; children: any }): JSX.Element {
    return (
        <div className="SitePopover__section">
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
            <ProfilePicture name={user?.first_name} email={user?.email} size="xl" />
            <div className="AccountInfo__identification SitePopover__main-info">
                <strong>{user?.first_name}</strong>
                <div className="supplement" title={user?.email}>
                    {user?.email}
                </div>
            </div>
            <Tooltip title="Account settings" placement="left">
                <LemonButton
                    to={urls.settings('user')}
                    onClick={closeSitePopover}
                    data-attr="top-menu-item-me"
                    status="stealth"
                    icon={<IconSettings className="text-2xl" />}
                />
            </Tooltip>
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
                    <strong>{organization.name}</strong>
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
    const { systemStatus } = useValues(navigationLogic)

    return (
        <LemonRow
            status={systemStatus ? 'success' : 'danger'}
            icon={systemStatus ? <IconCheckmark /> : <IconOffline />}
            fullWidth
        >
            <>
                <div className="SitePopover__main-info">
                    {systemStatus ? 'All systems operational' : 'Potential system issue'}
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
    const { featureFlags } = useValues(featureFlagLogic)
    const { closeSitePopover } = useActions(navigationLogic)
    const { showFeaturePreviewsModal } = useActions(featurePreviewsLogic)

    const isUsingSiteApp = featureFlags[FEATURE_FLAGS.EARLY_ACCESS_FEATURE_SITE_BUTTON] === 'site-app'

    return (
        <LemonButton
            onClick={() => {
                closeSitePopover()
                if (!isUsingSiteApp) {
                    showFeaturePreviewsModal()
                }
            }}
            data-attr={isUsingSiteApp ? 'early-access-feature-button' : undefined}
            icon={<IconFeatures />}
            fullWidth
        >
            Feature previews
        </LemonButton>
    )
}

function ThemeSwitcher(): JSX.Element {
    const { user } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <LemonSelect
            options={[
                { icon: <IconLaptop />, value: null, label: `Theme synced with system` },
                { icon: <IconDay />, value: 'light', label: 'Light mode' },
                { icon: <IconNight />, value: 'dark', label: 'Dark mode' },
            ]}
            value={user?.theme_mode}
            onChange={(value) => updateUser({ theme_mode: value })}
            type="tertiary"
            fullWidth
            dropdownPlacement="right-start"
        />
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
                <SitePopoverSection title="PostHog instance">
                    <SystemStatus />
                    <AsyncMigrations />
                    <InstanceSettings />
                </SitePopoverSection>
            )}
            <SitePopoverSection>
                <FlaggedFeature flag={FEATURE_FLAGS.POSTHOG_3000}>
                    <ThemeSwitcher />
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
                <FlaggedFeature flag={FEATURE_FLAGS.EARLY_ACCESS_FEATURE_SITE_BUTTON}>
                    <FeaturePreviewsButton />
                </FlaggedFeature>
            </SitePopoverSection>
            <SitePopoverSection>
                <SignOutButton />
            </SitePopoverSection>
        </>
    )
}

export function SitePopover(): JSX.Element {
    const { user } = useValues(userLogic)
    const { isSitePopoverOpen, systemStatus } = useValues(navigationLogic)
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
                    <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
                    {!systemStatus && <IconExclamation className="SitePopover__danger" />}
                </div>
                <IconArrowDropDown />
            </div>
        </Popover>
    )
}
