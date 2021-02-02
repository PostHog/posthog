import React from 'react'
import { useValues } from 'kea'
import { Alert } from 'antd'
import { StarOutlined, SettingOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { LinkButton } from 'lib/components/LinkButton'
import { Link } from 'lib/components/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function DemoWarning(): JSX.Element | null {
    const { user, demoOnlyProject } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!demoOnlyProject) {
        return null
    }

    return (
        <>
            <Alert
                type="warning"
                message={`Get started using Posthog, ${user?.name}!`}
                className="demo-warning"
                description={
                    <span>
                        You're currently viewing <b>demo data</b>. Go to <Link to="/setup">setup</Link> to start sending
                        your own data
                    </span>
                }
                icon={<StarOutlined />}
                showIcon
                action={
                    <LinkButton to="/setup">
                        <SettingOutlined /> Go to setup
                    </LinkButton>
                }
                closable
                style={featureFlags['navigation-1775'] ? { marginTop: 32 } : undefined}
            />
        </>
    )
}
