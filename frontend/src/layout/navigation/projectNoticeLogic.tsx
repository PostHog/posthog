import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { IconGear, IconPlus } from '@posthog/icons'

import api from 'lib/api'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { LemonBannerProps } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { eventIngestionRestrictionLogic } from 'lib/logic/eventIngestionRestrictionLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { verifyEmailLogic } from 'scenes/authentication/signup/verify-email/verifyEmailLogic'
import { billingLogic, BillingAlertConfig } from 'scenes/billing/billingLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { ProxyRecord } from 'scenes/settings/environment/proxyLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import type { projectNoticeLogicType } from './projectNoticeLogicType'

export type ProjectNoticeVariant =
    | 'billing_alert'
    | 'demo_project'
    | 'real_project_with_no_events'
    | 'invite_teammates'
    | 'unverified_email'
    | 'internet_connection_issue'
    | 'event_ingestion_restriction'
    | 'missing_reverse_proxy'

export interface ProjectNoticeBlueprint {
    message: JSX.Element | string
    action?: LemonBannerProps['action']
    type?: LemonBannerProps['type']
    onClose?: LemonBannerProps['onClose']
    mountNoEventsBannerLogic?: boolean
}

const NOTICE_DISMISS_PREFIX = 'project-notice-dismissed.'

function isNoticeDismissed(key: string): boolean {
    try {
        return localStorage.getItem(NOTICE_DISMISS_PREFIX + key) === 'true'
    } catch {
        return false
    }
}

function storeNoticeDismissal(key: string): void {
    try {
        localStorage.setItem(NOTICE_DISMISS_PREFIX + key, 'true')
    } catch {
        /* noop */
    }
}

function buildBillingAlertNotice(
    billingAlert: BillingAlertConfig,
    canAccessBilling: boolean,
    currentPathname: string
): ProjectNoticeBlueprint {
    const showButton =
        billingAlert.action || billingAlert.contactSupport || currentPathname !== urls.organizationBilling()

    const action = billingAlert.action
        ? billingAlert.action
        : billingAlert.contactSupport
          ? {
                to: 'mailto:sales@posthog.com',
                children: billingAlert.buttonCTA || 'Contact support',
                onClick: () => billingLogic.actions.reportBillingAlertActionClicked(billingAlert),
            }
          : canAccessBilling
            ? {
                  to: urls.organizationBilling(),
                  children: 'Manage billing',
                  onClick: () => billingLogic.actions.reportBillingAlertActionClicked(billingAlert),
              }
            : undefined

    return {
        message: (
            <>
                <b>{billingAlert.title}</b>
                <br />
                {billingAlert.message}
            </>
        ),
        type: billingAlert.status,
        action: showButton ? action : undefined,
        onClose: billingAlert.onClose,
    }
}

export const projectNoticeLogic = kea<projectNoticeLogicType>([
    path(['layout', 'navigation', 'projectNoticeLogic']),
    connect(() => ({
        values: [membersLogic, ['memberCount'], organizationLogic, ['currentOrganizationId']],
        actions: [eventUsageLogic, ['reportProjectNoticeDismissed', 'reportProjectNoticeShown']],
    })),
    actions({
        dismissProjectNotice: (dismissKey: string | null) => ({ dismissKey }),
        reportNoticeShown: true,
    }),
    loaders(({ values }) => ({
        proxyRecords: {
            __default: null as null | ProxyRecord[],
            loadRecords: async () => {
                const response = await api.get(`api/organizations/${values.currentOrganizationId}/proxy_records`)
                return response.results
            },
        },
    })),
    reducers({
        // Suppress all notices for the rest of the session after any dismiss
        noticeDismissedThisSession: [false, { dismissProjectNotice: () => true }],
    }),
    selectors({
        effectiveBillingAlert: [
            () => [billingLogic.selectors.billingAlert, superpowersLogic.selectors.fakeBillingAlert],
            (billingAlert, fakeBillingAlert): BillingAlertConfig | null => {
                if (fakeBillingAlert !== 'none') {
                    return {
                        status: fakeBillingAlert,
                        title: `Fake ${fakeBillingAlert} billing alert`,
                        message: 'This is a fake billing alert triggered via Superpowers for testing purposes.',
                    }
                }
                return billingAlert
            },
        ],
        projectNoticeVariant: [
            (s) => [
                organizationLogic.selectors.currentOrganization,
                teamLogic.selectors.currentTeam,
                preflightLogic.selectors.preflight,
                userLogic.selectors.user,
                s.memberCount,
                apiStatusLogic.selectors.internetConnectionIssue,
                eventIngestionRestrictionLogic.selectors.hasProjectNoticeRestriction,
                s.proxyRecords,
                s.effectiveBillingAlert,
                router.selectors.currentLocation,
                s.noticeDismissedThisSession,
            ],
            (
                organization,
                currentTeam,
                preflight,
                user,
                memberCount,
                internetConnectionIssue,
                hasEventIngestionRestriction,
                proxyRecords,
                effectiveBillingAlert,
                currentLocation,
                noticeDismissedThisSession
            ): ProjectNoticeVariant | null => {
                if (!organization) {
                    return null
                }

                if (noticeDismissedThisSession) {
                    return null
                }

                if (internetConnectionIssue) {
                    return 'internet_connection_issue'
                } else if (
                    effectiveBillingAlert &&
                    !(effectiveBillingAlert.pathName && currentLocation.pathname !== effectiveBillingAlert.pathName) &&
                    !(
                        effectiveBillingAlert.dismissKey &&
                        isNoticeDismissed(`billing_alert.${effectiveBillingAlert.dismissKey}`)
                    )
                ) {
                    return 'billing_alert'
                } else if (currentTeam?.is_demo && !preflight?.demo) {
                    // If the project is a demo one, show a project-level warning
                    // Don't show this project-level warning in the PostHog demo environemnt though,
                    // as then Announcement is shown instance-wide
                    return 'demo_project'
                } else if (!user?.is_email_verified && !user?.has_social_auth && preflight?.email_service_available) {
                    return 'unverified_email'
                } else if (
                    !isNoticeDismissed('real_project_with_no_events') &&
                    currentTeam &&
                    !currentTeam.ingested_event
                ) {
                    return 'real_project_with_no_events'
                } else if (hasEventIngestionRestriction) {
                    return 'event_ingestion_restriction'
                } else if (
                    // Only show the reverse proxy nudge during the first 7 days of each month.
                    // Showing it all the time causes people to ignore it — surfacing it periodically
                    // keeps it noticeable and drives more adoption.
                    new Date().getDate() <= 7 &&
                    !isNoticeDismissed('missing_reverse_proxy') &&
                    proxyRecords !== null &&
                    proxyRecords.length === 0
                ) {
                    return 'missing_reverse_proxy'
                } else if (!isNoticeDismissed('invite_teammates') && memberCount === 1) {
                    return 'invite_teammates'
                }

                return null
            },
        ],
        projectNoticeDismissKey: [
            (s) => [s.projectNoticeVariant, s.effectiveBillingAlert],
            (variant, effectiveBillingAlert): string | null => {
                switch (variant) {
                    case 'billing_alert':
                        return effectiveBillingAlert?.dismissKey
                            ? `billing_alert.${effectiveBillingAlert.dismissKey}`
                            : null
                    case 'real_project_with_no_events':
                    case 'missing_reverse_proxy':
                    case 'invite_teammates':
                        return variant
                    default:
                        return null
                }
            },
        ],
        projectNotice: [
            (s) => [
                s.projectNoticeVariant,
                s.effectiveBillingAlert,
                s.projectNoticeDismissKey,
                organizationLogic.selectors.currentOrganization,
                userLogic.selectors.user,
                billingLogic.selectors.canAccessBilling,
                router.selectors.currentLocation,
                sceneLogic.selectors.activeSceneProductKey,
            ],
            (
                variant,
                effectiveBillingAlert,
                dismissKey,
                currentOrganization,
                user,
                canAccessBilling,
                currentLocation,
                activeSceneProductKey
            ): ProjectNoticeBlueprint | null => {
                if (!variant) {
                    return null
                }

                const dismiss = dismissKey
                    ? () => projectNoticeLogic.actions.dismissProjectNotice(dismissKey)
                    : undefined

                switch (variant) {
                    case 'billing_alert': {
                        if (!effectiveBillingAlert) {
                            return null
                        }
                        const notice = buildBillingAlertNotice(
                            effectiveBillingAlert,
                            canAccessBilling,
                            currentLocation.pathname
                        )
                        const canClose = dismiss || notice.onClose
                        return {
                            ...notice,
                            onClose: canClose
                                ? () => {
                                      notice.onClose?.()
                                      projectNoticeLogic.actions.dismissProjectNotice(dismissKey)
                                  }
                                : undefined,
                        }
                    }
                    case 'demo_project': {
                        const altTeam = currentOrganization?.teams?.find(
                            (team) => !team.is_demo && !team.ingested_event
                        )
                        return {
                            message: (
                                <>
                                    This is a demo project with dummy data.
                                    {altTeam && (
                                        <>
                                            {' '}
                                            When you're ready, head on over to the{' '}
                                            <Link
                                                to={urls.project(altTeam.id, urls.onboarding())}
                                                data-attr="demo-project-alt-team-ingestion_link"
                                            >
                                                onboarding flow
                                            </Link>{' '}
                                            to get started with your own data.
                                        </>
                                    )}
                                </>
                            ),
                        }
                    }
                    case 'real_project_with_no_events':
                        return {
                            message: (
                                <>
                                    This project has no events yet. Go to the{' '}
                                    <Link
                                        to={urls.onboarding({
                                            productKey: activeSceneProductKey ?? ProductKey.PRODUCT_ANALYTICS,
                                            stepKey: OnboardingStepKey.INSTALL,
                                        })}
                                        data-attr="real_project_with_no_events-ingestion_link"
                                    >
                                        onboarding flow
                                    </Link>{' '}
                                    or grab your project API key/HTML snippet from{' '}
                                    <Link to={urls.settings()} data-attr="real_project_with_no_events-settings">
                                        Project Settings
                                    </Link>{' '}
                                    to get things moving
                                </>
                            ),
                            action: {
                                to: urls.onboarding({
                                    productKey: activeSceneProductKey ?? ProductKey.PRODUCT_ANALYTICS,
                                    stepKey: OnboardingStepKey.INSTALL,
                                }),
                                'data-attr': 'demo-warning-cta',
                                icon: <IconGear />,
                                children: 'Go to onboarding',
                            },
                            onClose: dismiss,
                            mountNoEventsBannerLogic: true,
                        }
                    case 'invite_teammates':
                        return {
                            message: 'Get more out of PostHog by inviting your team for free',
                            action: {
                                'data-attr': 'invite-warning-cta',
                                onClick: () => inviteLogic.actions.showInviteModal(),
                                icon: <IconPlus />,
                                children: 'Invite team members',
                            },
                            onClose: dismiss,
                        }
                    case 'unverified_email':
                        return {
                            message: 'Please verify your email address.',
                            action: {
                                'data-attr': 'unverified-email-cta',
                                onClick: () => user && verifyEmailLogic.actions.requestVerificationLink(user.uuid),
                                children: 'Send verification email',
                            },
                            type: 'warning',
                        }
                    case 'internet_connection_issue':
                        return {
                            message:
                                'PostHog is having trouble connecting to the server. Please check your connection.',
                            type: 'warning',
                            action: {
                                'data-attr': 'reload-page',
                                onClick: () => window.location.reload(),
                                children: 'Reload page',
                            },
                        }
                    case 'event_ingestion_restriction':
                        return {
                            message:
                                'Event ingestion restrictions have been applied to a token in this project. Please contact support.',
                            type: 'warning',
                        }
                    case 'missing_reverse_proxy':
                        return {
                            message: (
                                <>
                                    Ad blockers can silently drop 10-25% of your events. Set up a{' '}
                                    <Link
                                        to={urls.settings('organization-proxy')}
                                        data-attr="missing-reverse-proxy-settings_link"
                                    >
                                        reverse proxy
                                    </Link>{' '}
                                    to route data through your own domain and prevent this.
                                </>
                            ),
                            type: 'info',
                            onClose: dismiss,
                        }
                    default:
                        return null
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        dismissProjectNotice: ({ dismissKey }) => {
            if (dismissKey) {
                storeNoticeDismissal(dismissKey)
            }
            actions.reportProjectNoticeDismissed(dismissKey ?? values.projectNoticeVariant ?? 'unknown')
        },
        reportNoticeShown: () => {
            if (values.projectNoticeVariant) {
                actions.reportProjectNoticeShown(values.projectNoticeVariant)
            }
            if (values.projectNoticeVariant === 'billing_alert' && values.effectiveBillingAlert) {
                billingLogic.actions.reportBillingAlertShown(values.effectiveBillingAlert)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRecords()
    }),
])
