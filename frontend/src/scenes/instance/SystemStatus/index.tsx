import './index.scss'

import { Alert } from 'antd'
import { systemStatusLogic, InstanceStatusTabName } from './systemStatusLogic'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { IconInfo, IconOpenInNew } from 'lib/lemon-ui/icons'
import { OverviewTab } from 'scenes/instance/SystemStatus/OverviewTab'
import { InternalMetricsTab } from 'scenes/instance/SystemStatus/InternalMetricsTab'
import { SceneExport } from 'scenes/sceneTypes'
import { InstanceConfigTab } from './InstanceConfigTab'
import { userLogic } from 'scenes/userLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { StaffUsersTab } from './StaffUsersTab'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { KafkaInspectorTab } from './KafkaInspectorTab'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export const scene: SceneExport = {
    component: SystemStatus,
    logic: systemStatusLogic,
}

export function SystemStatus(): JSX.Element {
    const { tab, error } = useValues(systemStatusLogic)
    const { setTab } = useActions(systemStatusLogic)
    const { preflight, siteUrlMisconfigured } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    let tabs = [
        {
            key: 'overview',
            label: (
                <Tooltip title={<>System overview is cached for 60 seconds</>}>
                    System overview <IconInfo />
                </Tooltip>
            ),
            content: <OverviewTab />,
        },
    ] as LemonTab<InstanceStatusTabName>[]

    if (user?.is_staff) {
        tabs = tabs.concat([
            {
                key: 'metrics',
                label: 'Internal metrics',
                content: <InternalMetricsTab />,
            },
            {
                key: 'settings',
                label: (
                    <>
                        Settings{' '}
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </>
                ),
                content: <InstanceConfigTab />,
            },
            {
                key: 'staff_users',
                label: 'Staff Users',
                content: <StaffUsersTab />,
            },
        ])

        if (featureFlags[FEATURE_FLAGS.KAFKA_INSPECTOR]) {
            tabs.push({
                key: 'kafka_inspector',
                label: (
                    <>
                        Kafka Inspector{' '}
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </>
                ),
                content: <KafkaInspectorTab />,
            })
        }
    }

    return (
        <div className="system-status-scene">
            <PageHeader
                title="Instance status & settings"
                caption={
                    <>
                        Here you can find all the critical runtime details and settings of your PostHog instance. You
                        have access to this because you're a <b>staff user</b>.{' '}
                        <a
                            target="_blank"
                            style={{ display: 'inline-flex', alignItems: 'center' }}
                            href="https://posthog.com/docs/self-host/configure/instance-settings?utm_medium=in-product&utm_campaign=instance_status"
                        >
                            Learn more <IconOpenInNew style={{ marginLeft: 4 }} />
                        </a>
                        .
                    </>
                }
            />
            {error && (
                <Alert
                    message="Something went wrong"
                    description={error || <span>An unknown error occurred. Please try again or contact us.</span>}
                    type="error"
                    showIcon
                />
            )}
            {siteUrlMisconfigured && (
                <Alert
                    message="Misconfiguration detected"
                    description={
                        <>
                            Your <code>SITE_URL</code> environment variable seems misconfigured. Your{' '}
                            <code>SITE_URL</code> is set to{' '}
                            <b>
                                <code>{preflight?.site_url}</code>
                            </b>{' '}
                            but you're currently browsing this page from{' '}
                            <b>
                                <code>{window.location.origin}</code>
                            </b>
                            . In order for PostHog to work properly, please set this to the origin where your instance
                            is hosted.{' '}
                            <a
                                target="_blank"
                                rel="noopener"
                                href="https://posthog.com/docs/configuring-posthog/environment-variables?utm_medium=in-product&utm_campaign=system-status-site-url-misconfig"
                            >
                                Learn more <IconOpenInNew />
                            </a>
                        </>
                    }
                    showIcon
                    type="warning"
                    style={{ marginBottom: 32 }}
                />
            )}

            <LemonTabs activeKey={tab} onChange={setTab} tabs={tabs} />
        </div>
    )
}
