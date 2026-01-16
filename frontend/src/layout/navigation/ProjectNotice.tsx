import { useActions, useValues } from 'kea'

import { IconGear, IconPlus } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { verifyEmailLogic } from 'scenes/authentication/signup/verify-email/verifyEmailLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { ProjectNoticeVariant, navigationLogic } from './navigationLogic'

interface ProjectNoticeBlueprint {
    message: JSX.Element | string
    action?: LemonBannerAction
    type?: 'info' | 'warning' | 'success' | 'error'
    closeable?: boolean
}

export function ProjectNotice({ className }: { className?: string }): JSX.Element | null {
    const { projectNoticeVariant } = useValues(navigationLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { user } = useValues(userLogic)
    const { closeProjectNotice } = useActions(navigationLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { requestVerificationLink } = useActions(verifyEmailLogic)
    const { sceneConfig, productFromUrl } = useValues(sceneLogic)

    if (!projectNoticeVariant) {
        return null
    }

    const altTeamForIngestion = currentOrganization?.teams?.find((team) => !team.is_demo && !team.ingested_event)

    const NOTICES: Record<ProjectNoticeVariant, ProjectNoticeBlueprint> = {
        demo_project: {
            message: (
                <>
                    This is a demo project with dummy data.
                    {altTeamForIngestion && (
                        <>
                            {' '}
                            When you're ready, head on over to the{' '}
                            <Link
                                to={urls.project(altTeamForIngestion.id, urls.onboarding())}
                                data-attr="demo-project-alt-team-ingestion_link"
                            >
                                onboarding wizard
                            </Link>{' '}
                            to get started with your own data.
                        </>
                    )}
                </>
            ),
        },

        real_project_with_no_events: {
            message: (
                <>
                    This project has no events yet. Go to the{' '}
                    <Link
                        to={urls.onboarding({
                            productKey: productFromUrl ?? ProductKey.PRODUCT_ANALYTICS,
                            stepKey: OnboardingStepKey.INSTALL,
                        })}
                        data-attr="real_project_with_no_events-ingestion_link"
                    >
                        onboarding wizard
                    </Link>{' '}
                    or grab your project API key/HTML snippet from{' '}
                    <Link to={urls.settings()} data-attr="real_project_with_no_events-settings">
                        Project Settings
                    </Link>{' '}
                    to get things moving
                </>
            ),
            action: {
                to: urls.onboarding({
                    productKey: productFromUrl ?? ProductKey.PRODUCT_ANALYTICS,
                    stepKey: OnboardingStepKey.INSTALL,
                }),
                'data-attr': 'demo-warning-cta',
                icon: <IconGear />,
                children: 'Go to wizard',
            },
            closeable: true,
        },
        invite_teammates: {
            message: 'Get more out of PostHog by inviting your team for free',
            action: {
                'data-attr': 'invite-warning-cta',
                onClick: showInviteModal,
                icon: <IconPlus />,
                children: 'Invite team members',
            },
            closeable: true,
        },
        unverified_email: {
            message: 'Please verify your email address.',
            action: {
                'data-attr': 'unverified-email-cta',
                onClick: () => user && requestVerificationLink(user.uuid),
                children: 'Send verification email',
            },
            type: 'warning',
        },
        internet_connection_issue: {
            message: 'PostHog is having trouble connecting to the server. Please check your connection.',
            type: 'warning',
            action: {
                'data-attr': 'reload-page',
                onClick: () => window.location.reload(),
                children: 'Reload page',
            },
        },

        event_ingestion_restriction: {
            message:
                'Event ingestion restrictions have been applied to a token in this project. Please contact support.',
            type: 'warning',
        },
    }

    const relevantNotice = NOTICES[projectNoticeVariant]

    const requiresHorizontalMargin =
        sceneConfig?.layout && ['app-raw', 'app-raw-no-header'].includes(sceneConfig.layout)

    return (
        <LemonBanner
            type={relevantNotice.type || 'info'}
            className={cn('my-4', requiresHorizontalMargin && 'mx-4', className)}
            action={relevantNotice.action}
            onClose={relevantNotice.closeable ? () => closeProjectNotice(projectNoticeVariant) : undefined}
        >
            {relevantNotice.message}
        </LemonBanner>
    )
}
