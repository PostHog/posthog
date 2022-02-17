import { Alert, Layout } from 'antd'
import { useValues } from 'kea'
import { BillingAlerts } from 'lib/components/BillingAlerts'
import { getAppContext } from 'lib/utils/getAppContext'
import React from 'react'
import { SwapOutlined } from '@ant-design/icons'
import { sceneLogic } from 'scenes/sceneLogic'
import { Breadcrumbs } from './Breadcrumbs/Breadcrumbs'
import { DemoWarnings } from './DemoWarnings/DemoWarnings'
import { SideBar } from './SideBar/SideBar'
import { TopBar } from './TopBar/TopBar'
import { teamLogic } from 'scenes/teamLogic'

export function Navigation({ children }: { children: any }): JSX.Element {
    const { sceneConfig } = useValues(sceneLogic)
    const { currentTeam } = useValues(teamLogic)

    const preswitchTeamName = getAppContext()?.preswitch_team_name

    return (
        <Layout style={{ minHeight: '100vh' }}>
            <TopBar />
            <SideBar>
                <Layout.Content className={!sceneConfig?.plain ? 'main-app-content' : undefined}>
                    {!sceneConfig?.plain && (
                        <>
                            {preswitchTeamName && (
                                <Alert
                                    type="info"
                                    message={`This item belongs to a different project than the one you were in – automatically switched you from "${preswitchTeamName}" to "${currentTeam?.name}".`}
                                    icon={<SwapOutlined />}
                                    showIcon
                                    closable
                                    style={{ marginTop: '1.5rem' }}
                                />
                            )}
                            {!sceneConfig?.hideDemoWarnings && <DemoWarnings />}
                            <BillingAlerts />
                            <Breadcrumbs />
                        </>
                    )}
                    {children}
                </Layout.Content>
            </SideBar>
        </Layout>
    )
}
