import { useMountedLogic, useValues } from 'kea'
import { Suspense, useEffect } from 'react'
import { Slide, ToastContainer } from 'react-toastify'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { productSetupPreloadLogic } from 'lib/components/ProductEmptyState/productSetupPreloadLogic'
import { globalSetupLogic, useSetupHighlight } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { billingLogic } from 'lib/logic/billing/billingLogic'
import { eventIngestionRestrictionLogic } from 'lib/logic/eventIngestionRestrictionLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { runWhenIdle } from 'lib/utils/async'
import { isEmbeddedPageFrame } from 'lib/utils/embeddedPageFrame'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'
import { WizardHandoffDialog } from 'scenes/onboarding/shared/wizard-sync/WizardHandoffDialog'
import { WizardSyncDebugPanel } from 'scenes/onboarding/shared/wizard-sync/WizardSyncDebugPanel'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { GlobalModals } from '~/layout/GlobalModals'
import { GlobalShortcuts } from '~/layout/GlobalShortcuts'
import { Navigation } from '~/layout/navigation-3000/Navigation'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { ImpersonationNotice } from '~/layout/navigation/ImpersonationNotice'

import { webmcpLogic } from 'products/webmcp/frontend/logics/webmcpLogic'

import { sceneLogic } from './sceneLogic'

const TerminalDock = lazyWithRetry(() =>
    import('./terminal/TerminalDock').then(({ TerminalDock }) => ({ default: TerminalDock }))
)
const importCommand = (): Promise<typeof import('lib/components/Command/Command')> =>
    import('lib/components/Command/Command')
const Command = lazyWithRetry(() => importCommand().then(({ Command }) => ({ default: Command })))
// Off the eager path but fetched on idle, so the first open skips the network. The lazy component retries a failed import.
function preloadCommand(withCommandKSearch: boolean): void {
    void importCommand().catch(() => {})
    if (withCommandKSearch) {
        void import('lib/components/CommandKSearch/CommandKSearch').catch(() => {})
    }
}
// Staff-only, so everyone else skips the chunk and the toolbar selector code it pulls in.
const InternalFeedbackWidget = lazyWithRetry(() =>
    import('~/layout/InternalFeedback/InternalFeedbackWidget').then(({ InternalFeedbackWidget }) => ({
        default: InternalFeedbackWidget,
    }))
)
// Deciding whether a run is active takes API polls, so the shell cannot gate these cheaply.
// Lazy loading keeps their logic and generated API clients off the first paint instead.
const WizardSyncFab = lazyWithRetry(() =>
    import('scenes/onboarding/shared/wizard-sync/WizardSyncFab').then(({ WizardSyncFab }) => ({
        default: WizardSyncFab,
    }))
)
const WizardRunSyncFab = lazyWithRetry(() =>
    import('products/wizard/frontend/runs/WizardRunSyncFab').then(({ WizardRunSyncFab }) => ({
        default: WizardRunSyncFab,
    }))
)

export default function AuthenticatedShell({ children }: { children: React.ReactNode }): JSX.Element {
    useMountedLogic(apiStatusLogic)
    useMountedLogic(eventIngestionRestrictionLogic)
    useMountedLogic(breadcrumbsLogic)
    useMountedLogic(globalSetupLogic)
    useMountedLogic(webmcpLogic)
    useMountedLogic(billingLogic)
    // Resolves product setup statuses on idle, so gated scenes open without a spinner.
    useMountedLogic(productSetupPreloadLogic)
    useSetupHighlight()

    const { sceneConfig } = useValues(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { user } = useValues(userLogic)
    const { hasOpenedCommand } = useValues(commandLogic)
    const newCommandKSearch = !!featureFlags[FEATURE_FLAGS.NEW_COMMAND_K_SEARCH]
    useEffect(
        () => (isEmbeddedPageFrame() ? undefined : runWhenIdle(() => preloadCommand(newCommandKSearch))),
        [newCommandKSearch]
    )
    const showInternalFeedback =
        !!featureFlags[FEATURE_FLAGS.INTERNAL_FEEDBACK_WIDGET] && !!user?.email?.toLowerCase().endsWith('@posthog.com')
    const runSyncEnabled = featureFlags[FEATURE_FLAGS.WIZARD_RUN_SYNC] === 'wizard-run'
    const toasts = (
        <ToastContainer
            autoClose={6000}
            transition={Slide}
            closeButton={<ToastCloseButton />}
            position="bottom-right"
            theme={isDarkModeOn ? 'dark' : 'light'}
        />
    )

    // The page around the frame already has the command palette, shortcuts and floating buttons.
    if (isEmbeddedPageFrame()) {
        return (
            <>
                <div className="contents isolate">
                    <Navigation sceneConfig={sceneConfig}>{children}</Navigation>
                    <GlobalModals />
                </div>
                {toasts}
            </>
        )
    }

    return (
        <>
            <div className="contents isolate">
                <Navigation sceneConfig={sceneConfig}>{children}</Navigation>
                <GlobalModals />
                <GlobalShortcuts />
                {featureFlags[FEATURE_FLAGS.POSTHOG_TERMINAL] && (
                    <ErrorBoundary className="fixed bottom-0 inset-x-0 max-h-[60vh] overflow-auto z-modal bg-surface-primary">
                        <Suspense fallback={null}>
                            <TerminalDock />
                        </Suspense>
                    </ErrorBoundary>
                )}
                {hasOpenedCommand && (
                    <ErrorBoundary>
                        <ChunkLoadErrorBoundary>
                            <Suspense fallback={null}>
                                <Command />
                            </Suspense>
                        </ChunkLoadErrorBoundary>
                    </ErrorBoundary>
                )}
                <ImpersonationNotice />
                <ErrorBoundary>
                    <ChunkLoadErrorBoundary>
                        <Suspense fallback={null}>{runSyncEnabled ? <WizardRunSyncFab /> : <WizardSyncFab />}</Suspense>
                    </ChunkLoadErrorBoundary>
                </ErrorBoundary>
                {/* Separate from the FAB: the FAB stands down while an inline panel shows the run,
                    but the doc dialog must be able to open from any surface. */}
                <WizardHandoffDialog />
                <WizardSyncDebugPanel />
                {showInternalFeedback && (
                    <ErrorBoundary>
                        <Suspense fallback={null}>
                            <InternalFeedbackWidget />
                        </Suspense>
                    </ErrorBoundary>
                )}
                {featureFlags[FEATURE_FLAGS.EXPERIMENTS_FREEZE_EXPOSURE_AA_TEST] === 'test' && (
                    <div data-attr="experiments-freeze-exposure-aa-test-variant" className="hidden" />
                )}
            </div>
            {toasts}
        </>
    )
}
