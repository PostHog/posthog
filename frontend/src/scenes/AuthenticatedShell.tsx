import { useMountedLogic, useValues } from 'kea'
import { Slide, ToastContainer } from 'react-toastify'

import { Command } from 'lib/components/Command/Command'
import { globalSetupLogic, useSetupHighlight } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { ToastCloseButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { eventIngestionRestrictionLogic } from 'lib/logic/eventIngestionRestrictionLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { WizardSyncDebugPanel } from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/WizardSync/WizardSyncDebugPanel'
import { WizardSyncFab } from 'scenes/onboarding/self-driving/sdks/OnboardingInstallStep/WizardSync/WizardSyncFab'

import { GlobalModals } from '~/layout/GlobalModals'
import { GlobalShortcuts } from '~/layout/GlobalShortcuts'
import { Navigation } from '~/layout/navigation-3000/Navigation'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { ImpersonationNotice } from '~/layout/navigation/ImpersonationNotice'
import { SelfReadOnlyNotice } from '~/layout/navigation/SelfReadOnlyNotice'

import { sceneLogic } from './sceneLogic'

export default function AuthenticatedShell({ children }: { children: React.ReactNode }): JSX.Element {
    useMountedLogic(apiStatusLogic)
    useMountedLogic(eventIngestionRestrictionLogic)
    useMountedLogic(breadcrumbsLogic)
    useMountedLogic(globalSetupLogic)
    useSetupHighlight()

    const { sceneConfig } = useValues(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <>
            <div className="contents isolate">
                <Navigation sceneConfig={sceneConfig}>{children}</Navigation>
                <GlobalModals />
                <GlobalShortcuts />
                <Command />
                <ImpersonationNotice />
                <SelfReadOnlyNotice />
                <WizardSyncFab />
                <WizardSyncDebugPanel />
                {featureFlags[FEATURE_FLAGS.EXPERIMENTS_DW_AA_TEST] === 'test' && (
                    <div data-attr="experiments-dw-aa-test-variant" className="hidden" />
                )}
            </div>
            <ToastContainer
                autoClose={6000}
                transition={Slide}
                closeButton={<ToastCloseButton />}
                position="bottom-right"
                theme={isDarkModeOn ? 'dark' : 'light'}
            />
        </>
    )
}
