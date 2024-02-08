import './index.scss'

import { LemonBanner, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconInfo } from 'lib/lemon-ui/icons'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { InternalMetricsTab } from 'scenes/instance/SystemStatus/InternalMetricsTab'
import { OverviewTab } from 'scenes/instance/SystemStatus/OverviewTab'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { InstanceConfigTab } from './InstanceConfigTab'
import { KafkaInspectorTab } from './KafkaInspectorTab'
import { StaffUsersTab } from './StaffUsersTab'
import { InstanceStatusTabName, systemStatusLogic } from './systemStatusLogic'

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
                <Tooltip title="System overview is cached for 60 seconds">
                    <span>
                        System overview <IconInfo />
                    </span>
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
                        <LemonTag type="warning" className="uppercase ml-1">
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
                        <LemonTag type="warning" className="uppercase ml-1">
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
                caption={
                    <>
                        Here you can find all the critical runtime details and settings of your PostHog instance. You
                        have access to this because you're a <b>staff user</b>.{' '}
                        <Link
                            target="_blank"
                            targetBlankIcon
                            to="https://posthog.com/docs/self-host/configure/instance-settings?utm_medium=in-product&utm_campaign=instance_status"
                        >
                            Learn more
                        </Link>
                        .
                    </>
                }
            />
            <div className="space-y-2">
                {error && (
                    <LemonBanner type="error">
                        <div>Something went wrong</div>
                        <div>{error || 'An unknown error occurred. Please try again or contact us.'}</div>
                    </LemonBanner>
                )}
                {siteUrlMisconfigured && (
                    <LemonBanner
                        type="warning"
                        action={{
                            children: 'Learn more',
                            to: 'https://posthog.com/docs/configuring-posthog/environment-variables?utm_medium=in-product&utm_campaign=system-status-site-url-misconfig',
                        }}
                    >
                        Your <code>SITE_URL</code> environment variable seems misconfigured. Your <code>SITE_URL</code>{' '}
                        is set to{' '}
                        <b>
                            <code>{preflight?.site_url}</code>
                        </b>{' '}
                        but you're currently browsing this page from{' '}
                        <b>
                            <code>{window.location.origin}</code>
                        </b>
                        . In order for PostHog to work properly, please set this to the origin where your instance is
                        hosted.
                    </LemonBanner>
                )}
            </div>

            <LemonTabs activeKey={tab} onChange={setTab} tabs={tabs} />
        </div>
    )
}
