import { kea, useMountedLogic, useValues, BindLogic, path, connect, actions, reducers, selectors, events } from 'kea'
import { ToastContainer, Slide } from 'react-toastify'
import { preflightLogic } from './PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { appLogicType } from './AppType'
import { teamLogic } from './teamLogic'
import { LoadedScene } from 'scenes/sceneTypes'
import { appScenes } from 'scenes/appScenes'
import { Navigation as NavigationClassic } from '~/layout/navigation/Navigation'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { ToastCloseButton } from 'lib/lemon-ui/lemonToast'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { inAppPromptLogic } from 'lib/logic/inAppPrompt/inAppPromptLogic'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { FEATURE_FLAGS } from 'lib/constants'
import { Navigation as Navigation3000 } from '~/layout/navigation-3000/Navigation'
import { useEffect } from 'react'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { GlobalModals } from '~/layout/GlobalModals'
import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'

export const appLogic = kea<appLogicType>([
    path(['scenes', 'App']),
    connect([teamLogic, organizationLogic, frontendAppsLogic, inAppPromptLogic, actionsModel, cohortsModel]),
    actions({
        enableDelayedSpinner: true,
        ignoreFeatureFlags: true,
    }),
    reducers({
        showingDelayedSpinner: [false, { enableDelayedSpinner: () => true }],
        featureFlagsTimedOut: [false, { ignoreFeatureFlags: () => true }],
    }),
    selectors({
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
    }),
    events(({ actions, cache }) => ({
        afterMount: () => {
            cache.spinnerTimeout = window.setTimeout(() => actions.enableDelayedSpinner(), 1000)
            cache.featureFlagTimeout = window.setTimeout(() => actions.ignoreFeatureFlags(), 3000)
        },
        beforeUnmount: () => {
            window.clearTimeout(cache.spinnerTimeout)
            window.clearTimeout(cache.featureFlagTimeout)
        },
    })),
])

export function App(): JSX.Element | null {
    const { showApp, showingDelayedSpinner } = useValues(appLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    useMountedLogic(sceneLogic({ scenes: appScenes }))

    useEffect(() => {
        if (featureFlags[FEATURE_FLAGS.POSTHOG_3000]) {
            document.body.classList.add('posthog-3000')
        } else {
            document.body.classList.remove('posthog-3000')
        }
    }, [featureFlags])

    if (showApp) {
        return (
            <>
                <LoadedSceneLogics />
                <AppScene />
            </>
        )
    }

    return <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />
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

function AppScene(): JSX.Element | null {
    useMountedLogic(breadcrumbsLogic)
    const { user } = useValues(userLogic)
    const { activeScene, activeLoadedScene, sceneParams, params, loadedScenes, sceneConfig } = useValues(sceneLogic)
    const { showingDelayedSpinner } = useValues(appLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const toastContainer = (
        <ToastContainer
            autoClose={6000}
            transition={Slide}
            closeOnClick={false}
            draggable={false}
            closeButton={<ToastCloseButton />}
            position="bottom-right"
            theme={isDarkModeOn ? 'dark' : 'light'}
        />
    )

    let sceneElement: JSX.Element
    if (activeScene && activeScene in loadedScenes) {
        const { component: SceneComponent } = loadedScenes[activeScene]
        sceneElement = <SceneComponent user={user} {...params} />
    } else {
        sceneElement = <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />
    }

    const wrappedSceneElement = (
        <ErrorBoundary key={activeScene}>
            {activeLoadedScene?.logic ? (
                <BindLogic logic={activeLoadedScene.logic} props={activeLoadedScene.paramsToProps?.(sceneParams) || {}}>
                    {sceneElement}
                </BindLogic>
            ) : (
                sceneElement
            )}
        </ErrorBoundary>
    )

    if (!user) {
        return sceneConfig?.onlyUnauthenticated || sceneConfig?.allowUnauthenticated ? (
            <>
                {wrappedSceneElement}
                {toastContainer}
            </>
        ) : null
    }

    const Navigation = featureFlags[FEATURE_FLAGS.POSTHOG_3000] ? Navigation3000 : NavigationClassic

    return (
        <>
            <Navigation sceneConfig={sceneConfig}>{wrappedSceneElement}</Navigation>
            {toastContainer}
            <GlobalModals />
        </>
    )
}
