import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ProjectTokenSnippet } from '../shared/ProjectTokenSnippet'
import { onboardingWelcomeLogic, WELCOME_PRODUCTS } from './onboardingWelcomeLogic'
import { WelcomeAiPanel } from './WelcomeAiPanel'
import { WelcomeProductNavItem } from './WelcomeProductNavItem'
import { WelcomeProductPanel } from './WelcomeProductPanel'

export const scene: SceneExport = {
    component: OnboardingWelcome,
    logic: onboardingWelcomeLogic,
}

export function OnboardingWelcome(): JSX.Element {
    const { selection } = useValues(onboardingWelcomeLogic)
    const { selectAi, selectProduct } = useActions(onboardingWelcomeLogic)

    return (
        <SceneContent>
            <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
                <div>
                    <h1 className="m-0 text-2xl font-semibold">Welcome to PostHog</h1>
                    <p className="m-0 mt-1 text-secondary">
                        Tell PostHog AI what you want to do, or set up a product yourself.
                    </p>
                </div>
                <ProjectTokenSnippet />
            </div>
            <div className="grid grid-cols-1 gap-4 @min-[56rem]/main-content:grid-cols-[18rem_minmax(0,1fr)]">
                {/* A wrapping row when the columns stack, so the panel stays near the top. */}
                <nav
                    className="flex min-w-0 flex-wrap gap-1 @min-[56rem]/main-content:flex-col @min-[56rem]/main-content:flex-nowrap @min-[56rem]/main-content:gap-px"
                    aria-label="Get started"
                >
                    <LemonButton
                        className="@min-[56rem]/main-content:w-full"
                        active={selection === 'ai'}
                        icon={<IconSparkles />}
                        onClick={() => selectAi()}
                        data-attr="onboarding-welcome-ai"
                    >
                        Ask PostHog AI
                    </LemonButton>
                    <div className="w-full px-2 pb-1 pt-3 text-xxs font-semibold uppercase tracking-wide text-tertiary">
                        Or install a specific product
                    </div>
                    {WELCOME_PRODUCTS.map(({ key, product }) => (
                        <WelcomeProductNavItem
                            key={key}
                            productKey={key}
                            product={product}
                            active={selection === key}
                            onSelect={() => selectProduct(key)}
                        />
                    ))}
                </nav>
                <LemonCard hoverEffect={false} className="min-w-0 p-4">
                    {selection === 'ai' ? <WelcomeAiPanel /> : <WelcomeProductPanel />}
                </LemonCard>
            </div>
        </SceneContent>
    )
}
