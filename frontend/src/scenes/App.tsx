import { BindLogic, BuiltLogic, useMountedLogic, useValues } from 'kea'
import { FEATURE_FLAGS, MOCK_NODE_PROCESS } from 'lib/constants'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { eventIngestionRestrictionLogic } from 'lib/logic/eventIngestionRestrictionLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Slide, ToastContainer } from 'react-toastify'
import { appScenes } from 'scenes/appScenes'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { GlobalModals } from '~/layout/GlobalModals'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { Navigation } from '~/layout/navigation-3000/Navigation'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { KeaDevtools } from 'lib/KeaDevTools'
import { appLogic } from 'scenes/appLogic'

window.process = MOCK_NODE_PROCESS

export function App(): JSX.Element | null {
    const { showApp, showingDelayedSpinner, showingDevTools } = useValues(appLogic)
    useMountedLogic(sceneLogic({ scenes: appScenes }))
    useMountedLogic(apiStatusLogic)
    useMountedLogic(eventIngestionRestrictionLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    useThemedHtml()

    // Old style persistence - no tabs, keep all loaded logics around forever ("turbo mode")
    // New style persistence - keep all open tabs around, discard logics when a tab is closed
    const useTurboModePersistence = !featureFlags[FEATURE_FLAGS.SCENE_TABS]

    if (showApp) {
        return (
            <>
                {useTurboModePersistence ? <LoadedSceneLogics /> : null}
                <AppScene />
                {showingDevTools ? <KeaDevtools /> : null}
            </>
        )
    }

    return <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />
}

function LoadedSceneLogic({ logic }: { logic: BuiltLogic }): null {
    if (!logic) {
        throw new Error('Loading scene without a logic')
    }
    useMountedLogic(logic)
    return null
}

function LoadedSceneLogics(): JSX.Element {
    const { loadedSceneLogics } = useValues(sceneLogic)
    return (
        <>
            {Object.entries(loadedSceneLogics)
                .filter(([_, logic]) => !!logic)
                .map(([key, logic]) => (
                    <LoadedSceneLogic key={key} logic={logic} />
                ))}
        </>
    )
}

function AppScene(): JSX.Element | null {
    useMountedLogic(breadcrumbsLogic)
    const { user } = useValues(userLogic)
    const {
        activeSceneId,
        activeLoadedScene,
        activeSceneComponentParamsWithTabId,
        activeSceneLogicPropsWithTabId,
        sceneConfig,
    } = useValues(sceneLogic)
    const { showingDelayedSpinner } = useValues(appLogic)
    const { isDarkModeOn } = useValues(themeLogic)

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
    if (activeLoadedScene?.component) {
        const { component: SceneComponent } = activeLoadedScene
        sceneElement = (
            <SceneComponent
                key={`tab-${activeSceneLogicPropsWithTabId.tabId}`}
                user={user}
                {...activeSceneComponentParamsWithTabId}
            />
        )
    } else {
        sceneElement = <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />
    }

    const wrappedSceneElement = (
        <ErrorBoundary
            key={`error-${activeSceneLogicPropsWithTabId.tabId}`}
            exceptionProps={{ feature: activeSceneId }}
        >
            {activeLoadedScene?.logic ? (
                <BindLogic
                    key={`bind-${activeSceneLogicPropsWithTabId.tabId}`}
                    logic={activeLoadedScene.logic}
                    props={activeSceneLogicPropsWithTabId}
                >
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

    return (
        <>
            <Navigation sceneConfig={sceneConfig}>{wrappedSceneElement}</Navigation>
            {toastContainer}
            <GlobalModals />
        </>
    )
}
