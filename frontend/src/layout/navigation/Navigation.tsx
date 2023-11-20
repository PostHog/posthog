import clsx from 'clsx'
import { BillingAlertsV2 } from 'lib/components/BillingAlertsV2'
import { SceneConfig } from 'scenes/sceneTypes'
import { Breadcrumbs } from './Breadcrumbs/Breadcrumbs'
import { ProjectNotice } from './ProjectNotice'
import { SideBar } from './SideBar/SideBar'
import { TopBar } from './TopBar/TopBar'
import { ReactNode } from 'react'

export function Navigation({
    children,
    sceneConfig,
}: {
    children: ReactNode
    sceneConfig: SceneConfig | null
}): JSX.Element {
    return (
        <div className="h-screen flex flex-col">
            <TopBar />
            <SideBar>
                <div
                    className={clsx(
                        'main-app-content',
                        sceneConfig?.layout === 'plain' && 'main-app-content--plain',
                        sceneConfig?.layout === 'app-container' && 'main-app-content--container'
                    )}
                >
                    {sceneConfig?.layout !== 'plain' && (
                        <>
                            <BillingAlertsV2 />
                            {!sceneConfig?.hideProjectNotice && <ProjectNotice />}
                            <Breadcrumbs />
                        </>
                    )}
                    {children}
                </div>
            </SideBar>
        </div>
    )
}
