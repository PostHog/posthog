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
import { Scene, sceneLogic, unauthenticatedRoutes } from 'scenes/sceneLogic'
import { SceneLoading } from 'lib/utils'
import { router } from 'kea-router'
import { CommandPalette } from 'lib/components/CommandPalette'
import { UpgradeModal } from './UpgradeModal'
import { teamLogic } from './teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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
function _App(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
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
            if (unauthenticatedRoutes.includes(scene)) {
                replace('/')
                return
            }

            // If user is in no organization, redirect to org creation, otherwise redirect away from org creation
            if (location.pathname.startsWith('/organization/create')) {
                if (user.organizations.length) {
                    replace('/')
                    return
                }
            } else if (!userLoading && !user.organizations.length) {
                replace('/organization/create')
                return
            }

            if (user.organization) {
                // If organization has no project, redirect to project creation, otherwise redirect away from it
                if (location.pathname.startsWith('/project/create')) {
                    if (user.organization.teams.length) {
                        replace('/')
                        return
                    }
                } else if (!userLoading && !user.organization.teams.length) {
                    replace('/project/create')
                    return
                }
            }
        }

        // If ingestion tutorial not completed, redirect to it
        if (
            currentTeam?.name &&
            !currentTeam.completed_snippet_onboarding &&
            !location.pathname.startsWith('/ingestion')
        ) {
            replace('/ingestion')
            return
        }
    }, [scene, user, currentTeam, currentTeamLoading])

    if (!user) {
        return unauthenticatedRoutes.includes(scene) ? (
            <Layout style={{ minHeight: '100vh' }}>
                <Scene {...params} /> <Toast />
            </Layout>
        ) : (
            <div />
        )
    }

    if (!scene || plainScenes.includes(scene)) {
        return (
            <Layout style={{ minHeight: '100vh' }}>
                <Scene user={user} {...params} />
                <Toast />
            </Layout>
        )
    }

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
                        <BillingToolbar />
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
