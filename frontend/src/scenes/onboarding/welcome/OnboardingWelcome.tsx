import { useActions, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

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
            <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
                <div>
                    <h1 className="text-2xl font-semibold m-0">Welcome to PostHog</h1>
                    <p className="text-secondary m-0 mt-1">
                        Install PostHog, then pick a product to see the rest of its setup.
                    </p>
                </div>
                <ProjectTokenSnippet />
            </div>
            <div className="grid grid-cols-1 gap-4 @min-[56rem]/main-content:grid-cols-[18rem_minmax(0,1fr)]">
                {/* A wrapping row when the columns stack, so the setup card stays near the top. */}
                <nav
                    className="flex flex-wrap gap-1 min-w-0 @min-[56rem]/main-content:flex-col @min-[56rem]/main-content:flex-nowrap @min-[56rem]/main-content:gap-px"
                    aria-label="Products"
                >
                    {products.map(({ key, product, completed }) => (
                        <LemonButton
                            key={key}
                            className="@min-[56rem]/main-content:w-full"
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
                <LemonCard hoverEffect={false} className="p-4 min-w-0">
                    {selectedProductKey ? (
                        <WelcomeProductSetup />
                    ) : (
                        <div className="flex items-center justify-center min-h-60" role="status" aria-label="Loading">
                            <Spinner className="text-2xl" />
                        </div>
                    )}
                </LemonCard>
            </div>
        </SceneContent>
    )
}
