import 'react-toastify/dist/ReactToastify.css'
import 'react-datepicker/dist/react-datepicker.css'
import { hot } from 'react-hot-loader/root'

import React, { useState, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { Layout } from 'antd'
import { ToastContainer, Slide } from 'react-toastify'

import { Sidebar } from '~/layout/Sidebar'
import { TopContent } from '~/layout/TopContent'
import { SendEventsOverlay } from '~/layout/SendEventsOverlay'
import { BillingToolbar } from 'lib/components/BillingToolbar'

import { userLogic } from 'scenes/userLogic'
import { sceneLogic, unauthenticatedRoutes } from 'scenes/sceneLogic'
import { SceneLoading } from 'lib/utils'
import { router } from 'kea-router'
import { CommandPalette } from 'lib/components/CommandPalette'
import { UpgradeModal } from './UpgradeModal'
import { teamLogic } from './teamLogic'

const darkerScenes: Record<string, boolean> = {
    dashboard: true,
    insights: true,
    funnel: true,
    editFunnel: true,
    paths: true,
}

export const App = hot(_App)
function _App(): JSX.Element {
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { scene, params, loadedScenes } = useValues(sceneLogic)
    const { location } = useValues(router)
    const { replace } = useActions(router)
    const [sidebarCollapsed, setSidebarCollapsed] = useState(typeof window !== 'undefined' && window.innerWidth <= 991)

    const Scene = loadedScenes[scene]?.component || (() => <SceneLoading />)

    useEffect(() => {
        // If user is already logged in, redirect away from unauthenticated routes like signup
        if (user && unauthenticatedRoutes.includes(scene)) {
            replace('/')
            return
        }

        // redirect to ingestion if not completed
        if (currentTeam && !currentTeam.completed_snippet_onboarding && !location.pathname.startsWith('/ingestion')) {
            replace('/ingestion')
            return
        }
    }, [scene, user])

    if (!user) {
        return unauthenticatedRoutes.includes(scene) ? (
            <>
                <Scene {...params} /> <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
            </>
        ) : (
            <div />
        )
    }

    if (scene === 'ingestion' || !scene) {
        return (
            <>
                <Scene user={user} {...params} />
                <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
            </>
        )
    }

    return (
        <>
            <UpgradeModal />
            <Layout className="bg-white">
                <Sidebar user={user} sidebarCollapsed={sidebarCollapsed} setSidebarCollapsed={setSidebarCollapsed} />
                <Layout
                    className={`${darkerScenes[scene] ? 'bg-dashboard' : 'bg-white'}${
                        !sidebarCollapsed ? ' with-open-sidebar' : ''
                    }`}
                    style={{ minHeight: '100vh' }}
                >
                    <TopContent />
                    <Layout.Content className="pl-5 pr-5 pt-3 pb-5" data-attr="layout-content">
                        <BillingToolbar />
                        {currentTeam &&
                        !currentTeam.ingested_event &&
                        !['project', 'organization', 'instance', 'my'].some((prefix) => scene.startsWith(prefix)) ? (
                            <SendEventsOverlay />
                        ) : (
                            <Scene user={user} {...params} />
                        )}
                        <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
                    </Layout.Content>
                </Layout>
            </Layout>
            <CommandPalette />
        </>
    )
}
