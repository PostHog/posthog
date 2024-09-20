import { IconGear, IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { useEffect, useState } from 'react'
import { verifyEmailLogic } from 'scenes/authentication/signup/verify-email/verifyEmailLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/types'

import { navigationLogic, ProjectNoticeVariant } from './navigationLogic'

interface ProjectNoticeBlueprint {
    message: JSX.Element | string
    action?: LemonBannerAction
    type?: 'info' | 'warning' | 'success' | 'error'
    closeable?: boolean
}

function CountDown({ datetime }: { datetime: dayjs.Dayjs }): JSX.Element {
    const [now, setNow] = useState(dayjs())

    useEffect(() => {
        const interval = setInterval(() => setNow(dayjs()), 1000)
        return () => clearInterval(interval)
    }, [])

    // Format the time difference as 00:00:00
    const duration = dayjs.duration(datetime.diff(now))
    const countdown = duration.hours() > 0 ? duration.format('HH:mm:ss') : duration.format('mm:ss')

    return <>{countdown}</>
}

export function ProjectNotice(): JSX.Element | null {
    const { projectNoticeVariant } = useValues(navigationLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { logout } = useActions(userLogic)
    const { user } = useValues(userLogic)
    const { closeProjectNotice } = useActions(navigationLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { requestVerificationLink } = useActions(verifyEmailLogic)
    const { openSupportForm } = useActions(supportLogic)

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
                                to={urls.project(altTeamForIngestion.id, urls.products())}
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
                        to={urls.onboarding(ProductKey.PRODUCT_ANALYTICS)}
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
                to: urls.onboarding(ProductKey.PRODUCT_ANALYTICS),
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
        is_impersonated: {
            message: (
                <>
                    You are currently logged in as a customer.{' '}
                    {user?.is_impersonated_until && (
                        <>
                            Expires in <CountDown datetime={dayjs(user.is_impersonated_until)} />
                        </>
                    )}
                </>
            ),
            type: 'warning',
            action: {
                'data-attr': 'stop-impersonation-cta',
                onClick: () => logout(),
                children: 'Log out',
            },
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
        region_blocked: {
            message:
                'PostHog is not available in your region due to legal restrictions. People in restricted regions will soon be blocked from accessing PostHog. Please contact support if you believe this is a mistake.',
            type: 'error',
            action: {
                'data-attr': 'region-blocked-support',
                onClick: () => openSupportForm({ kind: 'support', target_area: 'login' }),
                children: 'Contact support',
            },
        },
    }

    const relevantNotice = NOTICES[projectNoticeVariant]

    return (
        <LemonBanner
            type={relevantNotice.type || 'info'}
            className="my-4"
            action={relevantNotice.action}
            onClose={relevantNotice.closeable ? () => closeProjectNotice(projectNoticeVariant) : undefined}
        >
            {relevantNotice.message}
        </LemonBanner>
    )
}
