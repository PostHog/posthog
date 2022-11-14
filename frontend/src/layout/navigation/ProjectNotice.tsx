import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { navigationLogic } from './navigationLogic'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { AlertMessage } from 'lib/components/AlertMessage'
import { IconPlus, IconSettings } from 'lib/components/icons'
import { AlertMessageAction } from 'lib/components/AlertMessage/AlertMessage'

interface ProjectNoticeBlueprint {
    message: JSX.Element | string
    action?: AlertMessageAction
}

export function ProjectNotice(): JSX.Element | null {
    const { projectNoticeVariantWithClosability } = useValues(navigationLogic)
    const { closeProjectNotice } = useActions(navigationLogic)
    const { showInviteModal } = useActions(inviteLogic)

    if (!projectNoticeVariantWithClosability) {
        return null
    }

    const [projectNoticeVariant, isClosable] = projectNoticeVariantWithClosability

    const NOTICES: Record<'demo_project' | 'real_project_with_no_events' | 'invite_teammates', ProjectNoticeBlueprint> =
        {
            demo_project: {
                message: 'This is a demo project with dummy data',
            },
            real_project_with_no_events: {
                message: (
                    <>
                        This project has no events yet. Go to the{' '}
                        <Link to="/ingestion" data-attr="real_project_with_no_events-ingestion_link">
                            ingestion wizard
                        </Link>{' '}
                        or grab your project API key/HTML snippet from{' '}
                        <Link to="/project/settings" data-attr="real_project_with_no_events-settings">
                            Project Settings
                        </Link>{' '}
                        to get things moving
                    </>
                ),
                action: {
                    to: '/ingestion',
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
        }

    const relevantNotice = NOTICES[projectNoticeVariant]

    return (
        <AlertMessage
            type="info"
            className="my-6"
            action={relevantNotice.action}
            onClose={isClosable ? () => closeProjectNotice(projectNoticeVariant) : undefined}
        >
            {relevantNotice.message}
        </AlertMessage>
    )
}
