import { hot } from 'react-hot-loader/root'
import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { Layout } from 'antd'
import { ToastContainer, Slide } from 'react-toastify'

import { MainNavigation, TopNavigation, DemoWarnings } from '~/layout/navigation'
import { BillingAlerts } from 'lib/components/BillingAlerts'
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
import { BackTo } from 'lib/components/BackTo'
import { Papercups } from 'lib/components/Papercups'

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
    const { featureFlags } = useValues(featureFlagLogic)

    useEffect(() => {
        if (scene === Scene.Signup && preflight && !preflight.cloud && preflight.initiated) {
            // If user is on an initiated self-hosted instance, redirect away from signup
            replace('/login')
            return
        }
    }, [scene, preflight])

    useEffect(() => {
        if (user) {
            // If user is already logged in, redirect away from unauthenticated-only routes like signup
            if (sceneConfig.onlyUnauthenticated) {
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
        return sceneConfig.onlyUnauthenticated || sceneConfig.allowUnauthenticated ? (
            <Layout style={{ minHeight: '100vh' }}>
                <SceneComponent {...params} />
                {essentialElements}
            </Layout>
        ) : null
    }

    if (sceneConfig.plain) {
        return (
            <Layout style={{ minHeight: '100vh' }}>
                {!sceneConfig.hideTopNav && <TopNavigation />}
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
                <MainNavigation />
                <Layout className={`${sceneConfig.dark ? 'bg-mid' : ''}`} style={{ minHeight: '100vh' }}>
                    {!sceneConfig.hideTopNav && <TopNavigation />}
                    {scene ? (
                        <Layout.Content className="main-app-content" data-attr="layout-content">
                            {!sceneConfig.hideDemoWarnings && <DemoWarnings />}

                            <BillingAlerts />
                            <BackTo />
                            <SceneComponent user={user} {...params} />
                        </Layout.Content>
                    ) : null}
                </Layout>
                {essentialElements}
            </Layout>
            <CommandPalette />
        </>
    )
}
