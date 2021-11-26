import { Layout } from 'antd'
import { useValues } from 'kea'
import { BillingAlerts } from 'lib/components/BillingAlerts'
import React from 'react'
import { sceneLogic } from 'scenes/sceneLogic'
import { Breadcrumbs } from './Breadcrumbs/Breadcrumbs'
import { DemoWarnings } from './DemoWarnings/DemoWarnings'
import { SideBar } from './SideBar/SideBar'
import { TopBar } from './TopBar/TopBar'

export function Navigation({ children }: { children: any }): JSX.Element {
    const { sceneConfig } = useValues(sceneLogic)

    return (
        <Layout style={{ minHeight: '100vh' }}>
            <TopBar />
            <SideBar>
                <Layout.Content className={!sceneConfig?.plain ? 'main-app-content' : undefined}>
                    {!sceneConfig?.plain && (
                        <>
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
