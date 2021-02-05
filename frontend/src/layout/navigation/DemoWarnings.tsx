import React from 'react'
import { useValues } from 'kea'
import { Alert } from 'antd'
import { StarOutlined, SettingOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { LinkButton } from 'lib/components/LinkButton'
import { Link } from 'lib/components/Link'
import { navigationLogic } from './navigationLogic'

interface WarningInterface {
    message: JSX.Element | string
    description: JSX.Element | string
    action?: JSX.Element
}

interface WarningsInterface {
    incomplete_setup_on_demo_project: WarningInterface
    incomplete_setup_on_real_project: WarningInterface
    demo_project: WarningInterface
    real_project_with_no_events: WarningInterface
}

export function DemoWarnings(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { demoWarning } = useValues(navigationLogic)

    const WARNINGS: WarningsInterface = {
        incomplete_setup_on_demo_project: {
            message: `Get started using Posthog, ${user?.name}!`,
            description: (
                <span>
                    You're currently viewing <b>demo data</b>. Go to <Link to="/setup">setup</Link> to start sending
                    your own data
                </span>
            ),
            action: (
                <LinkButton to="/setup">
                    <SettingOutlined /> Go to setup
                </LinkButton>
            ),
        },
        incomplete_setup_on_real_project: {
            message: `Finish setting up Posthog, ${user?.name}!`,
            description: (
                <span>
                    You're very close. Go to <Link to="/setup">setup</Link> to finish up configuring PostHog.
                </span>
            ),
            action: (
                <LinkButton to="/setup">
                    <SettingOutlined /> Go to setup
                </LinkButton>
            ),
        },
        demo_project: {
            message: "You're viewing demo data.",
            description: <span>This is a demo project with dummy data.</span>,
        },
        real_project_with_no_events: {
            message: 'This project has no events yet.',
            description: (
                <>
                    We haven't received any events on this project. Go to the{' '}
                    <Link to="/ingestion">ingestion wizard</Link> or grab your snippet or API key directly on{' '}
                    <Link to="/project/settings">settings</Link> to get things moving.
                </>
            ),
            action: (
                <LinkButton to="/ingestion">
                    <SettingOutlined /> Go to wizard
                </LinkButton>
            ),
        },
    }

    if (!demoWarning) {
        return null
    }

    return (
        <>
            <Alert
                type="warning"
                message={WARNINGS[demoWarning].message}
                className="demo-warning"
                description={WARNINGS[demoWarning].description}
                icon={<StarOutlined />}
                showIcon
                action={WARNINGS[demoWarning].action}
                closable
                style={{ marginTop: 32 }}
            />
        </>
    )
}
