import React from 'react'
import { kea, useMountedLogic, useValues, BindLogic } from 'kea'
import { Layout } from 'antd'
import { ToastContainer, Slide } from 'react-toastify'
import { preflightLogic } from './PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Loading } from 'lib/utils'
import { UpgradeModal } from './UpgradeModal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { appLogicType } from './AppType'
import { models } from '~/models'
import { teamLogic } from './teamLogic'
import { LoadedScene } from 'scenes/sceneTypes'
import { appScenes } from 'scenes/appScenes'
import { Navigation } from '~/layout/navigation/Navigation'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { ToastCloseButton } from 'lib/components/lemonToast'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { actionableTooltipLogic } from 'lib/logic/actionableTooltipLogic'

export const appLogic = kea<appLogicType>({
    path: ['scenes', 'App'],
    connect: [teamLogic, organizationLogic, frontendAppsLogic, actionableTooltipLogic],
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
    useMountedLogic(sceneLogic({ scenes: appScenes }))

    if (showApp) {
        return (
            <>
                {user && currentTeamId ? <Models /> : null}
                <LoadedSceneLogics />
                <AppScene />
            </>
        )
    }

    return showingDelayedSpinner ? <Loading /> : null
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
    useMountedLogic(breadcrumbsLogic)
    const { user } = useValues(userLogic)
    const { activeScene, activeLoadedScene, sceneParams, params, loadedScenes, sceneConfig } = useValues(sceneLogic)
    const { showingDelayedSpinner } = useValues(appLogic)

    const SceneComponent: (...args: any[]) => JSX.Element | null =
        (activeScene ? loadedScenes[activeScene]?.component : null) ||
        (() => (showingDelayedSpinner ? <Loading /> : null))

    const toastContainer = (
        <ToastContainer
            autoClose={6000}
            transition={Slide}
            closeOnClick={false}
            draggable={false}
            closeButton={<ToastCloseButton />}
            position="bottom-right"
        />
    )

    const protectedBoundActiveScene = (
        <ErrorBoundary key={activeScene}>
            {activeLoadedScene?.logic ? (
                <BindLogic logic={activeLoadedScene.logic} props={activeLoadedScene.paramsToProps?.(sceneParams) || {}}>
                    <SceneComponent user={user} {...params} />
                </BindLogic>
            ) : (
                <SceneComponent user={user} {...params} />
            )}
        </ErrorBoundary>
    )

    if (!user) {
        return sceneConfig?.onlyUnauthenticated || sceneConfig?.allowUnauthenticated ? (
            <Layout style={{ minHeight: '100vh' }}>
                {protectedBoundActiveScene}
                {toastContainer}
            </Layout>
        ) : null
    }

    return (
        <>
            <Navigation>{protectedBoundActiveScene}</Navigation>
            {toastContainer}
            <UpgradeModal />
        </>
    )
}
