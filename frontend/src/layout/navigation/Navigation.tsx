import clsx from 'clsx'
import { useValues } from 'kea'
import { BillingAlertsV2 } from 'lib/components/BillingAlertsV2'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { Breadcrumbs } from './Breadcrumbs/Breadcrumbs'
import { ProjectNotice } from './ProjectNotice'
import { SideBar } from './SideBar/SideBar'
import { TopBar } from './TopBar/TopBar'

export function Navigation({ children }: { children: any }): JSX.Element {
    const { sceneConfig, activeScene } = useValues(sceneLogic)

    return (
        <div className="h-screen flex flex-col">
            {activeScene !== Scene.Ingestion && <TopBar />}
            <SideBar>
                <div className={clsx('main-app-content', sceneConfig?.layout === 'plain' && 'main-app-content--plain')}>
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
