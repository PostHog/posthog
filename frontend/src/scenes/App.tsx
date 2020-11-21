import { hot } from 'react-hot-loader/root'

import React, { useState, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { Layout } from 'antd'
import { ToastContainer, Slide } from 'react-toastify'

import { Sidebar } from '~/layout/Sidebar'
import { MainNavigation, TopNavigation } from '~/layout/navigation'
import { TopContent } from '~/layout/TopContent'
import { SendEventsOverlay } from '~/layout/SendEventsOverlay'
import { BillingToolbar } from 'lib/components/BillingToolbar'

import { userLogic } from 'scenes/userLogic'
import { Scene, sceneLogic, unauthenticatedScenes } from 'scenes/sceneLogic'
import { SceneLoading } from 'lib/utils'
import { router } from 'kea-router'
import { CommandPalette } from 'lib/components/CommandPalette'
import { UpgradeModal } from './UpgradeModal'
import { teamLogic } from './teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from './organizationLogic'

const darkerScenes: Record<string, boolean> = {
    dashboard: true,
    insights: true,
    funnel: true,
    editFunnel: true,
    paths: true,
}
const plainScenes: Scene[] = [Scene.Ingestion, Scene.OrganizationCreateFirst, Scene.ProjectCreateFirst]

function Toast(): JSX.Element {
    return <ToastContainer autoClose={8000} transition={Slide} position="top-right" />
}

export const App = hot(_App)
function _App(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { scene, params, loadedScenes } = useValues(sceneLogic)
    const { location } = useValues(router)
    const { replace } = useActions(router)
    // used for legacy navigation [Sidebar.js]
    const [sidebarCollapsed, setSidebarCollapsed] = useState(typeof window !== 'undefined' && window.innerWidth <= 991)
    const { featureFlags } = useValues(featureFlagLogic)

    const Scene = loadedScenes[scene]?.component || (() => <SceneLoading />)

    useEffect(() => {
        if (user) {
            // If user is already logged in, redirect away from unauthenticated routes like signup
            if (unauthenticatedScenes.includes(scene)) {
                replace('/')
                return
            }
            // Redirect to org/project creation if necessary
            if (!currentOrganizationLoading && !currentOrganization?.id) {
                if (location.pathname !== '/organization/create') replace('/organization/create')
                return
            } else if (!currentTeamLoading && !currentTeam?.id) {
                if (location.pathname !== '/project/create') replace('/project/create')
                return
            }
        }

        // If ingestion tutorial not completed, redirect to it
        if (
            currentTeam?.id &&
            !currentTeam.completed_snippet_onboarding &&
            !location.pathname.startsWith('/ingestion')
        ) {
            replace('/ingestion')
            return
        }
    }, [scene, user, currentOrganization, currentOrganizationLoading, currentTeam, currentTeamLoading])

    if (!user) {
        return unauthenticatedScenes.includes(scene) ? (
            <Layout style={{ minHeight: '100vh' }}>
                <Scene {...params} /> <Toast />
            </Layout>
        ) : null
    }

    if (!scene || plainScenes.includes(scene)) {
        return (
            <Layout style={{ minHeight: '100vh' }}>
                <Scene user={user} {...params} />
                <Toast />
            </Layout>
        )
    }

    if (!currentOrganization?.id || !currentTeam?.id) return null

    return (
        <>
            <UpgradeModal />
            <Layout>
                {featureFlags['navigation-1775'] ? (
                    <MainNavigation />
                ) : (
                    <Sidebar
                        user={user}
                        sidebarCollapsed={sidebarCollapsed}
                        setSidebarCollapsed={setSidebarCollapsed}
                    />
                )}
                <Layout
                    className={`${darkerScenes[scene] && 'bg-mid'}${
                        !featureFlags['navigation-1775'] && !sidebarCollapsed ? ' with-open-sidebar' : ''
                    }`}
                    style={{ minHeight: '100vh' }}
                >
                    {featureFlags['navigation-1775'] ? <TopNavigation /> : <TopContent />}
                    <Layout.Content className="main-app-content" data-attr="layout-content">
                        {!featureFlags['hide-billing-toolbar'] && <BillingToolbar />}
                        {currentTeam &&
                        !currentTeam.ingested_event &&
                        !['project', 'organization', 'instance', 'my'].some((prefix) => scene.startsWith(prefix)) ? (
                            <SendEventsOverlay />
                        ) : (
                            <Scene user={user} {...params} />
                        )}
                        <Toast />
                    </Layout.Content>
                </Layout>
            </Layout>
            <CommandPalette />
        </>
    )
}
