import './index.scss'

import React from 'react'
import { Alert, Tabs } from 'antd'
import { systemStatusLogic, TabName } from './systemStatusLogic'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { IconExternalLink } from 'lib/components/icons'
import { OverviewTab } from 'scenes/instance/SystemStatus/OverviewTab'
import { InternalMetricsTab } from 'scenes/instance/SystemStatus/InternalMetricsTab'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: SystemStatus,
    logic: systemStatusLogic,
}

export function SystemStatus(): JSX.Element {
    const { tab, error, systemStatus } = useValues(systemStatusLogic)
    const { setTab } = useActions(systemStatusLogic)
    const { preflight, siteUrlMisconfigured } = useValues(preflightLogic)

    return (
        <div className="system-status-scene">
            <PageHeader
                title="System Status"
                caption="Here you can find all the critical runtime details about your PostHog installation."
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
                                Learn more <IconExternalLink />
                            </a>
                        </>
                    }
                    showIcon
                    type="warning"
                    style={{ marginBottom: 32 }}
                />
            )}

            {systemStatus?.internal_metrics.clickhouse ? (
                <Tabs tabPosition="top" animated={false} activeKey={tab} onTabClick={(key) => setTab(key as TabName)}>
                    <Tabs.TabPane tab="Overview" key="overview">
                        <OverviewTab />
                    </Tabs.TabPane>
                    <Tabs.TabPane tab="Internal metrics" key="internal_metrics">
                        <InternalMetricsTab />
                    </Tabs.TabPane>
                </Tabs>
            ) : (
                <OverviewTab />
            )}
        </div>
    )
}
