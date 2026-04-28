import { BindLogic, useMountedLogic, useValues } from 'kea'
import { Slide, ToastContainer } from 'react-toastify'

import { Command } from 'lib/components/Command/Command'
import { globalSetupLogic, useSetupHighlight } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS, MOCK_NODE_PROCESS } from 'lib/constants'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'
import { KeaDevtools } from 'lib/KeaDevTools'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { eventIngestionRestrictionLogic } from 'lib/logic/eventIngestionRestrictionLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { appScenes } from 'scenes/appScenes'
import { PostOnboardingModal } from 'scenes/onboarding/PostOnboardingModal'
import { postOnboardingModalLogic } from 'scenes/onboarding/postOnboardingModalLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneExport, SceneTab } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { GlobalModals } from '~/layout/GlobalModals'
import { GlobalShortcuts } from '~/layout/GlobalShortcuts'
import { Navigation } from '~/layout/navigation-3000/Navigation'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { ImpersonationNotice } from '~/layout/navigation/ImpersonationNotice'
import { UserType } from '~/types'

import { MaxInstance } from './max/Max'

window.process = MOCK_NODE_PROCESS

export function App(): JSX.Element | null {
    const { showApp, showingDelayedSpinner, showingDevTools } = useValues(appLogic)

    useMountedLogic(sceneLogic({ scenes: appScenes }))
    useMountedLogic(apiStatusLogic)
    useMountedLogic(eventIngestionRestrictionLogic)
    useMountedLogic(globalSetupLogic)
    useMountedLogic(postOnboardingModalLogic)

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
        tabs,
        activeTabId,
        activeSceneId,
        activeExportedScene,
        activeSceneComponentParamsWithTabId,
        activeSceneLogicPropsWithTabId,
        exportedScenes,
        sceneConfig,
    } = useValues(sceneLogic)
    const { showingDelayedSpinner, hasExitedAIOnlyMode } = useValues(appLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const keepTabsMounted = !!featureFlags[FEATURE_FLAGS.KEEP_SCENE_TABS_MOUNTED]

    // Highlight any relevant element after navigation from the quick start guide
    useSetupHighlight()

    const toastContainer = (
        <ToastContainer
            autoClose={6000}
            transition={Slide}
            closeButton={<ToastCloseButton />}
            position="bottom-right"
            theme={isDarkModeOn ? 'dark' : 'light'}
        />
    )

    if (featureFlags[FEATURE_FLAGS.AI_ONLY_MODE] && !hasExitedAIOnlyMode) {
        return (
            <>
                <div
                    className="fixed inset-0 bg-surface-secondary flex flex-col overflow-auto"
                    ref={() => {
                        // HACK: Normally DebugNotice removes the HTML-level debug bar, but in this case we don't have the nav rendering DebugNotice
                        document.getElementById('bottom-notice')?.remove()
                    }}
                >
                    <MaxInstance tabId="ai-only-mode" sidePanel isAIOnlyMode />
                </div>
                {toastContainer}
            </>
        )
    }

    let wrappedSceneElement: JSX.Element

    if (keepTabsMounted && user) {
        // Keep each tab's React tree mounted (hidden when inactive) so local state, scroll and form input survive tab switches.
        const hasActiveLoadedScene = !!activeExportedScene?.component
        wrappedSceneElement = (
            <>
                {tabs.map((tab: SceneTab) => (
                    <MountedSceneTab
                        key={tab.id}
                        tab={tab}
                        isActive={tab.id === activeTabId}
                        exportedScene={tab.sceneId ? exportedScenes[tab.sceneId] : undefined}
                        user={user}
                    />
                ))}
                {!hasActiveLoadedScene && <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />}
            </>
        )
    } else {
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

        wrappedSceneElement = (
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
    }

    if (!user) {
        return sceneConfig?.onlyUnauthenticated || sceneConfig?.allowUnauthenticated ? (
            <>
                {wrappedSceneElement}
                {toastContainer}
            </>
        ) : null
    }

    return (
        <div className="contents isolate">
            <Navigation sceneConfig={sceneConfig}>{wrappedSceneElement}</Navigation>
            {toastContainer}
            <GlobalModals />
            <GlobalShortcuts />
            <Command />
            <PostOnboardingModal />
            <ImpersonationNotice />
            {featureFlags[FEATURE_FLAGS.EXPERIMENTS_DW_AA_TEST] === 'test' && (
                <div data-attr="experiments-dw-aa-test-variant" className="hidden" />
            )}
        </div>
    )
}

interface MountedSceneTabProps {
    tab: SceneTab
    isActive: boolean
    exportedScene: SceneExport | undefined
    user: UserType
}

function MountedSceneTab({ tab, isActive, exportedScene, user }: MountedSceneTabProps): JSX.Element | null {
    if (!exportedScene?.component || !tab.sceneId) {
        return null
    }

    const SceneComponent = exportedScene.component
    const sceneParams = tab.sceneParams ?? { params: {}, searchParams: {}, hashParams: {} }
    const componentProps = { ...sceneParams.params, tabId: tab.id }
    const logicProps = { tabId: tab.id, ...exportedScene.paramsToProps?.(sceneParams) }

    const sceneElement = <SceneComponent user={user} {...componentProps} />

    return (
        <div hidden={!isActive} className="contents" data-tab-id={tab.id} aria-hidden={!isActive}>
            <ErrorBoundary exceptionProps={{ feature: tab.sceneId }}>
                {exportedScene.logic ? (
                    <BindLogic logic={exportedScene.logic} props={logicProps}>
                        {sceneElement}
                    </BindLogic>
                ) : (
                    sceneElement
                )}
            </ErrorBoundary>
        </div>
    )
}
