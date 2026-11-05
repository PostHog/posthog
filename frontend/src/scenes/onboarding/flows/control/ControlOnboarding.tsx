import './ControlOnboarding.scss'

import clsx from 'clsx'
import { useMountedLogic, useValues } from 'kea'

import { Logo } from 'lib/brand'

import { onboardingWizardRunLogic } from 'products/wizard/frontend/views/onboarding/onboardingWizardRunLogic'

import { OnboardingFlowHost } from './OnboardingFlowHost'
import { onboardingLogic } from './onboardingLogic'
import { ProductSelectionShell } from './productSelection/ProductSelectionShell'

const CARD_CLASSES =
    'relative w-full min-h-0 flex flex-col overflow-visible p-0 sm:max-h-[calc(100dvh-7rem)] sm:overflow-y-auto sm:p-8 md:p-10 sm:bg-surface-primary sm:rounded-2xl sm:shadow-[0_16px_40px_rgb(20_44_72_/_18%)] sm:border sm:border-primary'

/** Renders product selection until a product is chosen, then hands off to the flow host. */
export function ControlOnboarding(): JSX.Element {
    useMountedLogic(onboardingLogic)
    const { productKey, currentTeam, user } = useValues(onboardingLogic)
    useMountedLogic(
        onboardingWizardRunLogic({ projectId: currentTeam ? String(currentTeam.id) : '', userId: user?.id ?? 0 })
    )

    return (
        <div className="OnboardingDottedBg min-h-screen flex flex-col items-center justify-center p-4 sm:p-6">
            <span className="block mb-6">
                <Logo size="lg" />
            </span>
            <div className={clsx(CARD_CLASSES, productKey ? 'max-w-5xl' : 'max-w-6xl')}>
                {productKey ? <OnboardingFlowHost /> : <ProductSelectionShell />}
            </div>
        </div>
    )
}
