import { hot } from 'react-hot-loader/root'

import React, { useState, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { Alert, Layout } from 'antd'
import { ToastContainer, Slide } from 'react-toastify'

import { Sidebar } from '~/layout/Sidebar'
import { MainNavigation, TopNavigation } from '~/layout/navigation'
import { TopContent } from '~/layout/TopContent'
import { BillingToolbar } from 'lib/components/BillingToolbar'

import { userLogic } from 'scenes/userLogic'
import { sceneLogic, Scene } from 'scenes/sceneLogic'
import { SceneLoading } from 'lib/utils'
import { router } from 'kea-router'
import { CommandPalette } from 'lib/components/CommandPalette'
import { UpgradeModal } from './UpgradeModal'
import { teamLogic } from './teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from './organizationLogic'
import { preflightLogic } from './PreflightCheck/logic'
import { Link } from 'lib/components/Link'
import { BackTo } from 'lib/components/BackTo'
import { Papercups } from 'lib/components/Papercups'
import { DemoWarning } from '~/layout/navigation/DemoWarning'

function Toast(): JSX.Element {
    return <ToastContainer autoClose={8000} transition={Slide} position="top-right" />
}

export const App = hot(_App)
function _App(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { scene, params, loadedScenes, sceneConfig } = useValues(sceneLogic)
    const { preflight } = useValues(preflightLogic)
    const { location } = useValues(router)
    const { replace } = useActions(router)
    // used for legacy navigation [Sidebar.js]
    const [sidebarCollapsed, setSidebarCollapsed] = useState(typeof window !== 'undefined' && window.innerWidth <= 991)
    const { featureFlags } = useValues(featureFlagLogic)

    useEffect(() => {
        if (scene === Scene.Signup && !preflight.cloud && preflight.initiated) {
            // If user is on an initiated self-hosted instance, redirect away from signup
            replace('/login')
            return
        }
    }, [scene, preflight])

    useEffect(() => {
        if (user) {
            // If user is already logged in, redirect away from unauthenticated routes like signup
            if (sceneConfig.unauthenticated) {
                replace('/')
                return
            }
            // Redirect to org/project creation if necessary
            if (!currentOrganizationLoading && !currentOrganization?.id) {
                if (location.pathname !== '/organization/create') {
                    replace('/organization/create')
                }
                return
            } else if (!currentTeamLoading && !currentTeam?.id) {
                if (location.pathname !== '/project/create') {
                    replace('/project/create')
                }
                return
            }
        }

        // If ingestion tutorial not completed, redirect to it
        if (
            currentTeam?.id &&
            !currentTeam.completed_snippet_onboarding &&
            !location.pathname.startsWith('/ingestion') &&
            !location.pathname.startsWith('/personalization')
        ) {
            replace('/ingestion')
            return
        }
    }, [scene, user, currentOrganization, currentOrganizationLoading, currentTeam, currentTeamLoading])

    const SceneComponent = loadedScenes[scene]?.component || (() => <SceneLoading />)

    const essentialElements = (
        // Components that should always be mounted inside Layout
        <>
            {featureFlags['papercups-enabled'] && <Papercups user={user} />}
            <Toast />
        </>
    )

    if (!user) {
        return sceneConfig.unauthenticated ? (
            <Layout style={{ minHeight: '100vh' }}>
                <SceneComponent {...params} />
                {essentialElements}
            </Layout>
        ) : null
    }

    if (!scene || sceneConfig.plain) {
        return (
            <Layout style={{ minHeight: '100vh' }}>
                {featureFlags['navigation-1775'] && !sceneConfig.hide_top_nav ? <TopNavigation /> : null}
                <SceneComponent user={user} {...params} />
                {essentialElements}
            </Layout>
        )
    }

    if (!currentOrganization?.id || !currentTeam?.id) {
        return null
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
                    className={`${sceneConfig.dark ? 'bg-mid' : ''}${
                        !featureFlags['navigation-1775'] && !sidebarCollapsed ? ' with-open-sidebar' : ''
                    }`}
                    style={{ minHeight: '100vh' }}
                >
                    {!sceneConfig.hide_top_nav && featureFlags['navigation-1775'] ? <TopNavigation /> : <TopContent />}
                    <Layout.Content className="main-app-content" data-attr="layout-content">
                        <DemoWarning />

                        {!featureFlags['hide-billing-toolbar'] && <BillingToolbar />}
                        {featureFlags['navigation-1775'] ? <BackTo /> : null}

                        {currentTeam && !currentTeam.ingested_event && (
                            <Alert
                                type="warning"
                                style={{ marginTop: featureFlags['navigation-1775'] ? '1rem' : 0 }}
                                message={
                                    <>
                                        You haven't sent any events to this project yet. Grab{' '}
                                        <Link to="/project/settings">a snippet or library</Link> to get started!
                                    </>
                                }
                            />
                        )}
                        <SceneComponent user={user} {...params} />
                    </Layout.Content>
                </Layout>
                {essentialElements}
            </Layout>
            <CommandPalette />
        </>
    )
}
