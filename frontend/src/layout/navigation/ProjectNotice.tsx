import { useActions, useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { navigationLogic, ProjectNoticeVariant } from './navigationLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { IconPlus, IconSettings } from 'lib/lemon-ui/icons'
import { LemonBannerAction } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { userLogic } from 'scenes/userLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'
import { verifyEmailLogic } from 'scenes/authentication/signup/verify-email/verifyEmailLogic'
import { ProductKey } from '~/types'

interface ProjectNoticeBlueprint {
    message: JSX.Element | string
    action?: LemonBannerAction
    type?: 'info' | 'warning' | 'success' | 'error'
}

export function ProjectNotice(): JSX.Element | null {
    const { projectNoticeVariantWithClosability } = useValues(navigationLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { updateCurrentTeam } = useActions(userLogic)
    const { user } = useValues(userLogic)
    const { closeProjectNotice } = useActions(navigationLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { requestVerificationLink } = useActions(verifyEmailLogic)

    if (!projectNoticeVariantWithClosability) {
        return null
    }

    const [projectNoticeVariant, isClosable] = projectNoticeVariantWithClosability

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
                                onClick={() => {
                                    updateCurrentTeam(altTeamForIngestion?.id, urls.products())
                                }}
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
                icon: <IconSettings />,
                children: 'Go to wizard',
            },
        },
        invite_teammates: {
            message: 'Get more out of PostHog by inviting your team for free',
            action: {
                'data-attr': 'invite-warning-cta',
                onClick: showInviteModal,
                icon: <IconPlus />,
                children: 'Invite team members',
            },
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
            message: 'You are currently impersonating another user.',
            type: 'warning',
        },
    }

    const relevantNotice = NOTICES[projectNoticeVariant]

    return (
        <LemonBanner
            type={relevantNotice.type || 'info'}
            className="my-6"
            action={relevantNotice.action}
            onClose={isClosable ? () => closeProjectNotice(projectNoticeVariant) : undefined}
        >
            {relevantNotice.message}
        </LemonBanner>
    )
}
