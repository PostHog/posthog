import { BindLogic, useMountedLogic, useValues } from 'kea'
import { Slide, ToastContainer } from 'react-toastify'

import { KeaDevtools } from 'lib/KeaDevTools'
import { MOCK_NODE_PROCESS } from 'lib/constants'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { eventIngestionRestrictionLogic } from 'lib/logic/eventIngestionRestrictionLogic'
import { appLogic } from 'scenes/appLogic'
import { appScenes } from 'scenes/appScenes'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { GlobalModals } from '~/layout/GlobalModals'
import { Navigation } from '~/layout/navigation-3000/Navigation'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'

window.process = MOCK_NODE_PROCESS

export function App(): JSX.Element | null {
    const { showApp, showingDelayedSpinner, showingDevTools } = useValues(appLogic)
    useMountedLogic(sceneLogic({ scenes: appScenes }))
    useMountedLogic(apiStatusLogic)
    useMountedLogic(eventIngestionRestrictionLogic)
    useMountedLogic(maxGlobalLogic)
    useThemedHtml()

    if (showApp) {
        return (
            <>
                <AppScene />
                {showingDevTools ? <KeaDevtools /> : null}
            </>
        )
    }

    return <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />
}

function AppScene(): JSX.Element | null {
    useMountedLogic(breadcrumbsLogic)
    const { user } = useValues(userLogic)
    const {
        activeSceneId,
        activeExportedScene,
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
    if (activeExportedScene?.component) {
        const { component: SceneComponent } = activeExportedScene
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
            {activeExportedScene?.logic ? (
                <BindLogic
                    key={`bind-${activeSceneLogicPropsWithTabId.tabId}`}
                    logic={activeExportedScene.logic}
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
