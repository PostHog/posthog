import 'react-toastify/dist/ReactToastify.css'
import 'react-datepicker/dist/react-datepicker.css'

import React, { useState } from 'react'
import { useValues } from 'kea'
import { Layout } from 'antd'
import { ToastContainer, Slide } from 'react-toastify'

import { Sidebar } from '~/layout/Sidebar'
import { TopContent } from '~/layout/TopContent'
import { SendEventsOverlay } from '~/layout/SendEventsOverlay'

import { userLogic } from 'scenes/userLogic'
import { sceneLogic, loadedScenes } from 'scenes/sceneLogic'
import { SceneLoading } from 'lib/utils'

const darkerScenes = {
    dashboard: true,
    trends: true,
    funnel: true,
    editFunnel: true,
    paths: true,
}

export default function App() {
    const { user } = useValues(userLogic)
    const { scene, params } = useValues(sceneLogic)
    const [sidebarCollapsed, setSidebarCollapsed] = useState(typeof window !== 'undefined' && window.innerWidth <= 991)

    const Scene = loadedScenes[scene]?.component || (() => <SceneLoading />)

    if (!user) {
        return null
    }

    return (
        <Layout className="bg-white">
            <Sidebar user={user} sidebarCollapsed={sidebarCollapsed} setSidebarCollapsed={setSidebarCollapsed} />
            <Layout
                className={`${darkerScenes[scene] ? 'bg-dashboard' : 'bg-white'}${
                    !sidebarCollapsed ? ' with-open-sidebar' : ''
                }`}
                style={{ height: '100vh' }}
            >
                <div className="content py-3 layout-top-content">
                    <TopContent user={user} />
                </div>
                <Layout.Content className="pl-5 pr-5 pt-3" data-attr="layout-content">
                    <SendEventsOverlay user={user} />
                    <Scene user={user} {...params} />
                    <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
                </Layout.Content>
            </Layout>
        </Layout>
    )
}
