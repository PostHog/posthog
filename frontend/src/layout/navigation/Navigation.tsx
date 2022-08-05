import { Layout } from 'antd'
import { useValues } from 'kea'
import { BillingAlerts } from 'lib/components/BillingAlerts'
import React from 'react'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { Breadcrumbs } from './Breadcrumbs/Breadcrumbs'
import { DemoWarnings } from './DemoWarnings/DemoWarnings'
import { SideBar } from './SideBar/SideBar'
import { TopBar } from './TopBar/TopBar'

export function Navigation({ children }: { children: any }): JSX.Element {
    const { sceneConfig, activeScene } = useValues(sceneLogic)
    const { onboardingSidebarEnabled } = useValues(ingestionLogic)

    return (
        <Layout>
            {(!onboardingSidebarEnabled || (onboardingSidebarEnabled && activeScene !== Scene.Ingestion)) && <TopBar />}
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
