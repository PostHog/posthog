import React from 'react'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
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
    const { projectNoticeVariant } = useValues(navigationLogic)
    const { reportProjectNoticeDismissed } = useActions(eventUsageLogic)
    const { showInviteModal } = useActions(inviteLogic)

    if (!projectNoticeVariant) {
        return null
    }

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
            onClose={() => reportProjectNoticeDismissed(projectNoticeVariant)}
        >
            {relevantNotice.message}
        </AlertMessage>
    )
}
