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

const darkerScenes = {
    dashboard: true,
    insights: true,
    funnel: true,
    editFunnel: true,
    paths: true,
}

function App() {
    const { user } = useValues(userLogic)
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
        if (user && !user.team.completed_snippet_onboarding && !location.pathname.startsWith('/ingestion')) {
            replace('/ingestion')
            return
        }
    }, [scene, user])

    if (!user) {
        return (
            unauthenticatedRoutes.includes(scene) && (
                <>
                    <Scene {...params} />{' '}
                    <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
                </>
            )
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
            <Layout className="bg-white">
                <Sidebar user={user} sidebarCollapsed={sidebarCollapsed} setSidebarCollapsed={setSidebarCollapsed} />
                <Layout
                    className={`${darkerScenes[scene] ? 'bg-dashboard' : 'bg-white'}${
                        !sidebarCollapsed ? ' with-open-sidebar' : ''
                    }`}
                    style={{ minHeight: '100vh' }}
                >
                    <TopContent user={user} />
                    <Layout.Content className="pl-5 pr-5 pt-3" data-attr="layout-content">
                        <BillingToolbar />
                        {!user.has_events ? <SendEventsOverlay /> : <Scene user={user} {...params} />}
                        <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
                    </Layout.Content>
                </Layout>
            </Layout>
            <CommandPalette />
        </>
    )
}

export default hot(App)
