import { useActions, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ProjectTokenSnippet } from '../shared/ProjectTokenSnippet'
import { getProductIcon, toSentenceCase } from '../shared/utils'
import { onboardingWelcomeLogic } from './onboardingWelcomeLogic'
import { WelcomeProductSetup } from './WelcomeProductSetup'

export const scene: SceneExport = {
    component: OnboardingWelcome,
    logic: onboardingWelcomeLogic,
}

export function OnboardingWelcome(): JSX.Element {
    const { products, selectedProductKey } = useValues(onboardingWelcomeLogic)
    const { selectProduct } = useActions(onboardingWelcomeLogic)

    return (
        <SceneContent>
            <div>
                <h1 className="text-2xl font-semibold m-0">Welcome to PostHog</h1>
                <p className="text-secondary m-0 mt-1">
                    Pick the product you want to work on first to see how to set it up.
                </p>
            </div>
            <div className="grid grid-cols-1 gap-4 @min-[56rem]/main-content:grid-cols-[18rem_minmax(0,1fr)]">
                <div className="flex flex-col gap-4 min-w-0">
                    <LemonCard hoverEffect={false} className="p-4">
                        <ProjectTokenSnippet />
                    </LemonCard>
                    <nav className="flex flex-col gap-px" aria-label="Products">
                        {products.map(({ key, product, completed }) => (
                            <LemonButton
                                key={key}
                                fullWidth
                                active={key === selectedProductKey}
                                icon={getProductIcon(product.icon, { iconColor: product.iconColor })}
                                sideIcon={completed ? <IconCheckCircle className="text-success" /> : undefined}
                                tooltip={product.description}
                                tooltipPlacement="right"
                                onClick={() => selectProduct(key)}
                                data-attr={`onboarding-welcome-product-${key}`}
                            >
                                {toSentenceCase(product.name)}
                            </LemonButton>
                        ))}
                    </nav>
                </div>
                <LemonCard hoverEffect={false} className="p-4 min-w-0">
                    {selectedProductKey ? (
                        <WelcomeProductSetup />
                    ) : (
                        <div className="flex items-center justify-center text-center h-full min-h-60">
                            <p className="text-secondary m-0">Pick a product to see its setup steps here.</p>
                        </div>
                    )}
                </LemonCard>
            </div>
        </SceneContent>
    )
}
