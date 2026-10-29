import './Onboarding.scss'

import clsx from 'clsx'
import { useValues } from 'kea'

import { Logo } from 'lib/brand'
import { SceneExport } from 'scenes/sceneTypes'

import { OnboardingFlowHost } from './OnboardingFlowHost'
import { onboardingLogic } from './onboardingLogic'
import { ProductSelectionShell } from './productSelection/ProductSelectionShell'
import { SimpleOnboarding } from './simple/SimpleOnboarding'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

const CARD_CLASSES =
    'relative w-full min-h-0 flex flex-col overflow-visible p-0 sm:max-h-[calc(100dvh-7rem)] sm:overflow-y-auto sm:p-8 md:p-10 sm:bg-surface-primary sm:rounded-2xl sm:shadow-[0_16px_40px_rgb(30_50_10_/_25%)] sm:border sm:border-primary'

/**
 * Renders product selection until a product is chosen, then hands off to the flow host. The simple
 * flow skips product selection.
 */
export function Onboarding(): JSX.Element | null {
    const { productKey, flowVariant } = useValues(onboardingLogic)

    return (
        <div className="OnboardingDottedBg min-h-screen flex flex-col items-center justify-center p-4 sm:p-6">
            <span className="block mb-6">
                <Logo size="lg" />
            </span>
            <div className={clsx(CARD_CLASSES, productKey ? 'max-w-5xl' : 'max-w-6xl')}>
                {flowVariant === 'simple' ? (
                    <SimpleOnboarding />
                ) : productKey ? (
                    <OnboardingFlowHost />
                ) : (
                    <ProductSelectionShell />
                )}
            </div>
        </div>
    )
}
