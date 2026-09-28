import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip'
import { useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { PostHogProvider } from '@posthog/react'

import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { appLogic } from 'scenes/appLogic'
import { appScenes } from 'scenes/appScenes'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { GlobalModals } from '~/layout/GlobalModals'

import { EmbeddedSceneFrame } from './EmbeddedSceneFrame'

interface EmbeddedAppProps {
    theme: 'light' | 'dark'
    onSignOut: () => void
}

/**
 * The web app as it renders inside another shell: the active scene and the modals it opens, with no
 * navigation, side panel, command palette or global shortcuts, because the host provides those.
 */
export function EmbeddedApp({ theme, onSignOut }: EmbeddedAppProps): JSX.Element {
    useMountedLogic(sceneLogic({ scenes: appScenes }))
    useThemedHtml(false, theme)

    const { showApp, showingDelayedSpinner } = useValues(appLogic)
    const { user } = useValues(userLogic)
    // Popovers, modals and tooltips portal here instead of to `document.body`, so they stay inside the
    // embed root where the scoped stylesheet reaches them.
    const [floatingContainer, setFloatingContainer] = useState<HTMLDivElement | null>(null)

    return (
        <ErrorBoundary>
            <PostHogProvider client={posthog}>
                <BaseTooltip.Provider delay={500} closeDelay={0} timeout={400}>
                    <FloatingContainerContext.Provider value={floatingContainer}>
                        {!showApp ? (
                            <SpinnerOverlay sceneLevel visible={showingDelayedSpinner} />
                        ) : user ? (
                            <>
                                <EmbeddedSceneFrame />
                                <GlobalModals />
                            </>
                        ) : (
                            <div className="flex flex-col items-center justify-center gap-2 h-full p-4 text-center">
                                <p className="m-0">Your PostHog session ended. Sign in again to keep working.</p>
                                <LemonButton type="primary" onClick={onSignOut} data-attr="embedded-app-sign-in">
                                    Sign in again
                                </LemonButton>
                            </div>
                        )}
                        <div
                            ref={setFloatingContainer}
                            className="fixed inset-0 pointer-events-none z-[var(--z-top)] [&>*]:pointer-events-auto"
                        />
                        <ToastContainer
                            autoClose={6000}
                            transition={Slide}
                            closeButton={<ToastCloseButton />}
                            position="bottom-right"
                            theme={theme}
                        />
                    </FloatingContainerContext.Provider>
                </BaseTooltip.Provider>
            </PostHogProvider>
        </ErrorBoundary>
    )
}
