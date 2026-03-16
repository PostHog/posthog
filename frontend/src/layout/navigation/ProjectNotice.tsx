import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

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
import { OnboardingStepKey, TeamBasicType, UserType } from '~/types'

import { navigationLogic, ProjectNoticeVariant } from './navigationLogic'
import { noEventsBannerLogic } from './noEventsBannerLogic'

export interface ProjectNoticeBlueprint {
    message: JSX.Element | string
    action?: LemonBannerAction
    type?: 'info' | 'warning' | 'success' | 'error'
    closeable?: boolean
}

export interface NoticeProps {
    user: UserType | null
    altTeamForIngestion?: TeamBasicType
    showInviteModal: () => void
    requestVerificationLink: (userUuid: string) => void
}

export const NOTICES: Record<ProjectNoticeVariant, ((config: NoticeProps) => ProjectNoticeBlueprint) | null> = {
    real_project_with_no_events: null, // Custom handled below due to logic complexity
    demo_project: ({ altTeamForIngestion }) => ({
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
                            onboarding flow
                        </Link>{' '}
                        to get started with your own data.
                    </>
                )}
            </>
        ),
    }),
    invite_teammates: ({ showInviteModal }) => ({
        message: 'Get more out of PostHog by inviting your team for free',
        action: {
            'data-attr': 'invite-warning-cta',
            onClick: showInviteModal,
            icon: <IconPlus />,
            children: 'Invite team members',
        },
        closeable: true,
    }),
    unverified_email: ({ user, requestVerificationLink }) => ({
        message: 'Please verify your email address.',
        action: {
            'data-attr': 'unverified-email-cta',
            onClick: () => user && requestVerificationLink(user.uuid),
            children: 'Send verification email',
        },
        type: 'warning',
    }),
    internet_connection_issue: () => ({
        message: 'PostHog is having trouble connecting to the server. Please check your connection.',
        type: 'warning',
        action: {
            'data-attr': 'reload-page',
            onClick: () => window.location.reload(),
            children: 'Reload page',
        },
    }),
    event_ingestion_restriction: () => ({
        message: 'Event ingestion restrictions have been applied to a token in this project. Please contact support.',
        type: 'warning',
    }),
    missing_reverse_proxy: () => ({
        message: (
            <>
                Ad blockers can silently drop 10-25% of your events. Set up a{' '}
                <Link to={urls.settings('organization-proxy')} data-attr="missing-reverse-proxy-settings_link">
                    reverse proxy
                </Link>{' '}
                to route data through your own domain and prevent this.
            </>
        ),
        type: 'info',
        closeable: true,
    }),
}

export function ProjectNotice({ className }: { className?: string }): JSX.Element | null {
    const { projectNoticeVariant } = useValues(navigationLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { user } = useValues(userLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { requestVerificationLink } = useActions(verifyEmailLogic)
    const { sceneConfig } = useValues(sceneLogic)

    const notice = useMemo(() => {
        if (!projectNoticeVariant) {
            return null
        }

        const noticeFunc = NOTICES[projectNoticeVariant]
        if (!noticeFunc) {
            return null
        }

        return noticeFunc({
            user,
            altTeamForIngestion: currentOrganization?.teams?.find((team) => !team.is_demo && !team.ingested_event),
            showInviteModal,
            requestVerificationLink,
        })
    }, [projectNoticeVariant, user, currentOrganization, showInviteModal, requestVerificationLink])

    const requiresHorizontalMargin =
        sceneConfig?.layout && ['app-raw', 'app-raw-no-header'].includes(sceneConfig.layout)
    const bannerClassName = cn('my-4', requiresHorizontalMargin && 'mx-4', className)

    // Extra handling because we need to mount a logic for this one, so use separate component
    if (projectNoticeVariant === 'real_project_with_no_events') {
        return <NoEventsBanner className={bannerClassName} />
    }

    if (!notice || !projectNoticeVariant) {
        return null
    }

    return <Notice notice={notice} variant={projectNoticeVariant} className={bannerClassName} />
}

function NoEventsBanner({ className }: { className?: string }): JSX.Element {
    useMountedLogic(noEventsBannerLogic)
    const { activeSceneProductKey } = useValues(sceneLogic)
    const { closeProjectNotice } = useActions(navigationLogic)

    return (
        <LemonBanner
            type="info"
            className={className}
            action={{
                to: urls.onboarding({
                    productKey: activeSceneProductKey ?? ProductKey.PRODUCT_ANALYTICS,
                    stepKey: OnboardingStepKey.INSTALL,
                }),
                'data-attr': 'demo-warning-cta',
                icon: <IconGear />,
                children: 'Go to onboarding',
            }}
            onClose={() => closeProjectNotice('real_project_with_no_events')}
        >
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
        </LemonBanner>
    )
}

// Fully functional component to allow us to properly render a notice in the stories.tsx file
export const Notice = ({
    notice,
    variant,
    className,
}: {
    notice: ProjectNoticeBlueprint
    variant: ProjectNoticeVariant
    className?: string
}): JSX.Element => {
    const { closeProjectNotice } = useActions(navigationLogic)

    return (
        <LemonBanner
            type={notice.type || 'info'}
            className={className}
            action={notice.action}
            onClose={notice.closeable ? () => closeProjectNotice(variant) : undefined}
        >
            {notice.message}
        </LemonBanner>
    )
}
