import './AccountPopover.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IconCake,
    IconCheckCircle,
    IconConfetti,
    IconCopy,
    IconFeatures,
    IconGear,
    IconLeave,
    IconLive,
    IconPlusSmall,
    IconReceipt,
    IconServer,
    IconShieldLock,
} from '@posthog/icons'
import { LemonButtonPropsBase, LemonSelect } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { ThemeSwitcher } from 'scenes/settings/user/ThemeSwitcher'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { NewOrganizationButton, OtherOrganizationButton } from '~/layout/navigation/OrganizationSwitcher'
import { getTreeItemsGames } from '~/products'

import { preflightLogic } from '../../../scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { urls } from '../../../scenes/urls'
import { userLogic } from '../../../scenes/userLogic'
import { OrganizationBasicType, SidePanelTab } from '../../../types'
import { AccessLevelIndicator } from '../AccessLevelIndicator'
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
                to={urls.settings(user?.organization?.id ? 'user' : 'user-danger-zone')}
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
                    <div className="overflow-hidden text-secondary truncate text-[0.8125rem]" title={user?.email}>
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
        <LemonButton
            data-attr="top-menu-item-org-settings"
            icon={
                <UploadedLogo
                    name={organization.name}
                    entityId={organization.id}
                    mediaId={organization.logo_media_id}
                />
            }
            sideIcon={<IconGear />}
            fullWidth
            to={urls.settings('organization')}
            onClick={closeAccountPopover}
            tooltip="Organization settings"
            tooltipPlacement="left"
        >
            <div className="grow">
                <span className="font-medium">{organization.name}</span>
                <AccessLevelIndicator organization={organization} />
            </div>
        </LemonButton>
    )
}

function AccountOwner({ name, email }: { name: string; email: string }): JSX.Element {
    const { reportAccountOwnerClicked } = useActions(eventUsageLogic)

    return (
        <LemonButton
            onClick={() => {
                void copyToClipboard(email, 'email')
                reportAccountOwnerClicked({ name, email })
            }}
            fullWidth
            sideIcon={<IconCopy />}
            tooltip="This is your dedicated PostHog human. Click to copy their email. They can help you with trying out new products, solving problems, and reducing your spend."
        >
            <div className="flex items-center gap-2 grow">
                <ProfilePicture
                    user={{
                        first_name: name,
                        email: email,
                    }}
                    size="md"
                />
                <div>
                    <div className="font-medium truncate">{name}</div>
                    <div className="text-sm text-muted truncate">{email}</div>
                </div>
            </div>
        </LemonButton>
    )
}

export function InviteMembersButton({
    text = 'Invite members',
    center = false,
    type = 'tertiary',
    ...props
}: LemonButtonPropsBase & { text?: string }): JSX.Element {
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
            {...props}
        >
            {text}
        </LemonButton>
    )
}

function InstanceSettings(): JSX.Element {
    const { closeAccountPopover } = useActions(navigationLogic)

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

function DjangoAdmin(): JSX.Element {
    const { closeAccountPopover } = useActions(navigationLogic)

    return (
        <LemonButton
            icon={<IconShieldLock />}
            onClick={closeAccountPopover}
            fullWidth
            to="/admin/"
            disableClientSideRouting
            data-attr="top-menu-django-admin"
        >
            Django admin
        </LemonButton>
    )
}

function FeaturePreviewsButton(): JSX.Element {
    return (
        <LemonButton
            onClick={() => {
                router.actions.push(urls.settings('user-feature-previews'))
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
        <LemonButton onClick={logout} icon={<IconLeave />} fullWidth data-attr="top-menu-item-logout">
            Log out
        </LemonButton>
    )
}

export function AccountPopoverOverlay(): JSX.Element {
    const { user, otherOrganizations } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { preflight, isCloudOrDev, isCloud } = useValues(preflightLogic)
    const { closeAccountPopover } = useActions(navigationLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { billing } = useValues(billingLogic)

    return (
        <>
            <AccountPopoverSection title="Signed in as">
                <AccountInfo />
            </AccountPopoverSection>
            <AccountPopoverSection title="Current organization">
                {currentOrganization && <CurrentOrganization organization={currentOrganization} />}
                {isCloudOrDev ? (
                    <LemonButton
                        onClick={closeAccountPopover}
                        to={
                            featureFlags[FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]
                                ? urls.organizationBillingSection('overview')
                                : urls.organizationBilling()
                        }
                        icon={<IconReceipt />}
                        fullWidth
                        data-attr="top-menu-item-billing"
                    >
                        {featureFlags[FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS] ? 'Billing & Usage' : 'Billing'}
                    </LemonButton>
                ) : null}
                <InviteMembersButton />
                {billing?.account_owner?.email && billing?.account_owner?.name && (
                    <>
                        <h5 className="flex items-center mt-2">YOUR POSTHOG HUMAN</h5>
                        <AccountOwner name={billing.account_owner.name} email={billing.account_owner.email} />
                    </>
                )}
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
            </AccountPopoverSection>
            {featureFlags[FEATURE_FLAGS.GAME_CENTER] ? (
                <AccountPopoverSection>
                    <LemonSelect
                        options={getTreeItemsGames().map((game) => ({ label: game.path, value: game.href || '' }))}
                        value=""
                        renderButtonContent={() => 'Games'}
                        onChange={(value) => {
                            router.actions.push(String(value))
                            closeAccountPopover()
                        }}
                        dropdownPlacement="right-start"
                        dropdownMatchSelectWidth={false}
                        fullWidth
                        icon={<IconCake />}
                        type="tertiary"
                    />
                </AccountPopoverSection>
            ) : null}
            {user?.is_staff && (
                <AccountPopoverSection>
                    <DjangoAdmin />
                    <InstanceSettings />
                </AccountPopoverSection>
            )}
            {!isCloud && (
                <AccountPopoverSection>
                    <LemonButton
                        onClick={closeAccountPopover}
                        to={urls.moveToPostHogCloud()}
                        icon={<IconConfetti />}
                        fullWidth
                        data-attr="top-menu-item-upgrade-to-cloud"
                    >
                        Try PostHog Cloud
                    </LemonButton>
                </AccountPopoverSection>
            )}
            <AccountPopoverSection>
                <SignOutButton />
            </AccountPopoverSection>
        </>
    )
}
