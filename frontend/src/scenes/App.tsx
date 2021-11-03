import React from 'react'
import { kea, useMountedLogic, useValues } from 'kea'
import { Layout } from 'antd'
import { ToastContainer, Slide } from 'react-toastify'

import { preflightLogic } from './PreflightCheck/logic'
import { MainNavigation, TopNavigation, DemoWarnings } from '~/layout/navigation'
import { BillingAlerts } from 'lib/components/BillingAlerts'
import { userLogic } from 'scenes/userLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneLoading } from 'lib/utils'
import { UpgradeModal } from './UpgradeModal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { BackTo } from 'lib/components/BackTo'
import { appLogicType } from './AppType'
import { models } from '~/models'
import { FEATURE_FLAGS } from 'lib/constants'
import { CloudAnnouncement } from '~/layout/navigation/CloudAnnouncement'
import { teamLogic } from './teamLogic'
import { LoadedScene } from 'scenes/sceneTypes'
import { SideBar } from '../layout/lemonade/SideBar/SideBar'
import { appScenes } from 'scenes/appScenes'

export const appLogic = kea<appLogicType>({
    actions: {
        enableDelayedSpinner: true,
        ignoreFeatureFlags: true,
    },
    reducers: {
        showingDelayedSpinner: [false, { enableDelayedSpinner: () => true }],
        featureFlagsTimedOut: [false, { ignoreFeatureFlags: () => true }],
    },
    selectors: {
        showApp: [
            (s) => [
                userLogic.selectors.userLoading,
                userLogic.selectors.user,
                featureFlagLogic.selectors.receivedFeatureFlags,
                s.featureFlagsTimedOut,
                preflightLogic.selectors.preflightLoading,
                preflightLogic.selectors.preflight,
            ],
            (userLoading, user, receivedFeatureFlags, featureFlagsTimedOut, preflightLoading, preflight) => {
                return (
                    (!userLoading || user) &&
                    (receivedFeatureFlags || featureFlagsTimedOut) &&
                    (!preflightLoading || preflight)
                )
            },
        ],
    },
    events: ({ actions, cache }) => ({
        afterMount: () => {
            cache.spinnerTimeout = window.setTimeout(() => actions.enableDelayedSpinner(), 1000)
            cache.featureFlagTimeout = window.setTimeout(() => actions.ignoreFeatureFlags(), 3000)
        },
        beforeUnmount: () => {
            window.clearTimeout(cache.spinnerTimeout)
            window.clearTimeout(cache.featureFlagTimeout)
        },
    }),
})

export function App(): JSX.Element | null {
    const { showApp, showingDelayedSpinner } = useValues(appLogic)
    const { user } = useValues(userLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { sceneConfig } = useValues(sceneLogic({ scenes: appScenes }))
    const { featureFlags } = useValues(featureFlagLogic)

    if (showApp) {
        return (
            <>
                {user && currentTeamId ? <Models /> : null}
                {featureFlags[FEATURE_FLAGS.TURBO_MODE] ? <LoadedSceneLogics /> : null}
                {(!sceneConfig.projectBased || currentTeamId) && <AppScene />}
            </>
        )
    }

    return showingDelayedSpinner ? <SceneLoading /> : null
}

function LoadedSceneLogic({ scene }: { scene: LoadedScene }): null {
    if (!scene.logic) {
        throw new Error('Loading scene without a logic')
    }
    useMountedLogic(scene.logic(scene.paramsToProps?.(scene.sceneParams)))
    return null
}

function LoadedSceneLogics(): JSX.Element {
    const { loadedScenes } = useValues(sceneLogic)
    return (
        <>
            {Object.entries(loadedScenes)
                .filter(([, { logic }]) => !!logic)
                .map(([key, loadedScene]) => (
                    <LoadedSceneLogic key={key} scene={loadedScene} />
                ))}
        </>
    )
}

/** Loads every logic in the "src/models" folder */
function Models(): null {
    useMountedLogic(models)
    return null
}

function AppScene(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { activeScene, params, loadedScenes, sceneConfig } = useValues(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { showingDelayedSpinner } = useValues(appLogic)

    const SceneComponent: (...args: any[]) => JSX.Element | null =
        (activeScene ? loadedScenes[activeScene]?.component : null) ||
        (() => (showingDelayedSpinner ? <SceneLoading /> : null))

    const toastContainer = <ToastContainer autoClose={8000} transition={Slide} position="bottom-right" />

    if (!user) {
        return sceneConfig.onlyUnauthenticated || sceneConfig.allowUnauthenticated ? (
            <Layout style={{ minHeight: '100vh' }}>
                <SceneComponent {...params} />
                {toastContainer}
            </Layout>
        ) : null
    }

    if (sceneConfig.plain) {
        return (
            <Layout style={{ minHeight: '100vh' }}>
                {!sceneConfig.hideTopNav && <TopNavigation />}
                <SceneComponent user={user} {...params} />
                {toastContainer}
            </Layout>
        )
    }

    const layoutContent = activeScene ? (
        <Layout.Content className="main-app-content" data-attr="layout-content">
            {!sceneConfig.hideDemoWarnings && <DemoWarnings />}
            {featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT] && !featureFlags[FEATURE_FLAGS.LEMONADE] ? (
                <CloudAnnouncement message={String(featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT])} />
            ) : null}
            <BillingAlerts />
            <BackTo />
            <SceneComponent user={user} {...params} />
        </Layout.Content>
    ) : null

    return (
        <>
            {featureFlags[FEATURE_FLAGS.LEMONADE] ? (
                <Layout className={`${sceneConfig.dark ? 'bg-mid' : ''}`} style={{ minHeight: '100vh' }}>
                    {!sceneConfig.hideTopNav && <TopNavigation />}
                    <SideBar>{layoutContent}</SideBar>
                </Layout>
            ) : (
                <Layout>
                    <MainNavigation />
                    <Layout className={`${sceneConfig.dark ? 'bg-mid' : ''}`} style={{ minHeight: '100vh' }}>
                        {!sceneConfig.hideTopNav && <TopNavigation />}
                        {layoutContent}
                    </Layout>
                </Layout>
            )}
            {toastContainer}
            <UpgradeModal />
        </>
    )
}
