import clsx from 'clsx'
import { useValues } from 'kea'
import { BillingAlerts } from 'lib/components/BillingAlerts'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { Breadcrumbs } from './Breadcrumbs/Breadcrumbs'
import { ProjectNotice } from './ProjectNotice'
import { SideBar } from './SideBar/SideBar'
import { TopBar } from './TopBar/TopBar'

export function Navigation({ children }: { children: any }): JSX.Element {
    const { sceneConfig, activeScene } = useValues(sceneLogic)

    return (
        <div>
            {activeScene !== Scene.Ingestion && <TopBar />}
            <SideBar>
                <div className={clsx('main-app-content', sceneConfig?.plain && 'main-app-content--plain')}>
                    {!sceneConfig?.plain && (
                        <>
                            <BillingAlerts />
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
