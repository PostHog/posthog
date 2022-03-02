import React from 'react'
import { useActions, useValues } from 'kea'
import { Alert, Button } from 'antd'
import { StarOutlined, SettingOutlined, UserAddOutlined } from '@ant-design/icons'
import { LinkButton } from 'lib/components/LinkButton'
import { Link } from 'lib/components/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import './DemoWarnings.scss'
import { navigationLogic } from '../navigationLogic'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'

interface WarningInterface {
    message: JSX.Element | string
    description: JSX.Element | string
    action?: JSX.Element
    type?: 'warning' | 'info'
}

interface WarningsInterface {
    demo_project: WarningInterface
    real_project_with_no_events: WarningInterface
    invite_teammates: WarningInterface
}

export function DemoWarnings(): JSX.Element | null {
    const { demoWarning } = useValues(navigationLogic)
    const { reportDemoWarningDismissed } = useActions(eventUsageLogic)
    const { showInviteModal } = useActions(inviteLogic)

    const WARNINGS: WarningsInterface = {
        demo_project: {
            message: "You're viewing demo data.",
            description: <span>This is a demo project with dummy data.</span>,
        },
        real_project_with_no_events: {
            message: 'This project has no events yet.',
            description: (
                <>
                    We haven't received any events on this project. Go to the{' '}
                    <Link to="/ingestion" data-attr="real_project_with_no_events-ingestion_link">
                        ingestion wizard
                    </Link>{' '}
                    or grab your snippet or API key directly on{' '}
                    <Link to="/project/settings" data-attr="real_project_with_no_events-settings">
                        settings
                    </Link>{' '}
                    to get things moving.
                </>
            ),
            action: (
                <LinkButton
                    to="/ingestion"
                    data-attr="demo-warning-cta"
                    data-message="real_project_with_no_events-ingestion"
                >
                    <SettingOutlined /> Go to wizard
                </LinkButton>
            ),
        },
        invite_teammates: {
            message: 'Invite your team',
            description: <>Get more out of PostHog by inviting your team for free.</>,
            action: (
                <Button data-attr="invite-warning-cta" type="primary" onClick={showInviteModal}>
                    <UserAddOutlined />
                    Invite team members
                </Button>
            ),
            type: 'info',
        },
    }

    if (!demoWarning) {
        return null
    }

    return (
        <>
            <Alert
                type={WARNINGS[demoWarning].type || 'warning'}
                message={WARNINGS[demoWarning].message}
                className="demo-warning"
                description={WARNINGS[demoWarning].description}
                icon={<StarOutlined />}
                showIcon
                action={WARNINGS[demoWarning].action}
                closable
                style={{ marginTop: '1.5rem' }}
                onClose={() => reportDemoWarningDismissed(demoWarning)}
            />
        </>
    )
}
