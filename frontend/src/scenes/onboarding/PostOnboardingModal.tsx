import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowRight, IconCheckCircle } from '@posthog/icons'

import {
    BuilderHog1,
    DetectiveHog,
    ExperimentsHog,
    ExplorerHog,
    FeatureFlagHog,
    FilmCameraHog,
    GraphsHog,
    MailHog,
    MicrophoneHog,
    RobotHog,
    SupermanHog,
} from 'lib/components/hedgehogs'
import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { ProductKey } from '~/queries/schema/schema-general'

import { postOnboardingModalLogic } from './postOnboardingModalLogic'
import { availableOnboardingProducts, toSentenceCase } from './utils'

const HOGFETTI_OPTIONS = { count: 100, duration: 3000 }

/** What you'll unlock — capability + the problem it solves. */
const PRODUCT_VALUE_PROPS: Partial<Record<ProductKey, { title: string; problem: string }[]>> = {
    [ProductKey.PRODUCT_ANALYTICS]: [
        {
            title: 'Funnels & conversion tracking',
            problem: 'Find where users drop off in your signup or purchase flow',
        },
        { title: 'Trend analysis & dashboards', problem: 'Track how key metrics change week over week' },
        { title: 'User paths & retention', problem: 'Understand which features keep users coming back' },
    ],
    [ProductKey.WEB_ANALYTICS]: [
        { title: 'Traffic sources & referrals', problem: 'Know which channels bring your best users' },
        { title: 'Page performance metrics', problem: 'Find slow pages that hurt conversion' },
        { title: 'Conversion funnels', problem: 'See where visitors leave before converting' },
    ],
    [ProductKey.SESSION_REPLAY]: [
        { title: 'Session recordings', problem: 'See exactly where users get confused or stuck' },
        { title: 'Console & network logs', problem: 'Debug issues without asking users to reproduce them' },
        { title: 'Click & scroll heatmaps', problem: 'Find which parts of your pages get attention' },
    ],
    [ProductKey.FEATURE_FLAGS]: [
        { title: 'Targeted rollouts', problem: 'Ship to 5% of users before going to everyone' },
        { title: 'Release conditions', problem: 'Control who sees what based on properties or cohorts' },
        { title: 'Multivariate flags', problem: 'Test multiple variants without redeploying' },
    ],
    [ProductKey.EXPERIMENTS]: [
        { title: 'A/B testing', problem: 'Know which version actually performs better' },
        { title: 'Statistical analysis', problem: 'Get results you can trust, not gut feelings' },
        { title: 'Goal tracking', problem: 'Tie experiments directly to the metrics that matter' },
    ],
    [ProductKey.SURVEYS]: [
        { title: 'Targeted surveys', problem: 'Ask the right question at the right moment' },
        { title: 'In-app collection', problem: 'Get feedback without sending users to external forms' },
    ],
    [ProductKey.ERROR_TRACKING]: [
        { title: 'Automatic error capture', problem: 'Know about crashes before your users report them' },
        { title: 'Stack trace & context', problem: 'Jump straight to the line of code that broke' },
        { title: 'Issue management', problem: 'Prioritize fixes by how many users are affected' },
    ],
    [ProductKey.LLM_ANALYTICS]: [
        { title: 'Cost tracking per model', problem: 'See which LLM calls are burning your budget' },
        { title: 'Latency monitoring', problem: 'Find slow prompts before users complain' },
        { title: 'Prompt evaluation', problem: 'Compare prompt versions with real data' },
    ],
    [ProductKey.DATA_WAREHOUSE]: [
        { title: 'External data joins', problem: 'Combine Stripe, Hubspot, or Postgres data with PostHog' },
        { title: 'SQL queries', problem: 'Ask questions no pre-built dashboard can answer' },
    ],
    [ProductKey.REVENUE_ANALYTICS]: [
        { title: 'Revenue dashboards', problem: 'See MRR, churn, and LTV without building spreadsheets' },
        { title: 'Subscription tracking', problem: 'Understand which plans and cohorts drive growth' },
    ],
    [ProductKey.LOGS]: [
        { title: 'Centralized log collection', problem: 'Stop SSH-ing into servers to find what went wrong' },
        { title: 'Structured search', problem: 'Filter by level, service, or any property in seconds' },
    ],
    [ProductKey.WORKFLOWS]: [
        { title: 'Automated workflows', problem: 'Trigger Slack alerts, emails, or webhooks on any event' },
        { title: 'Custom logic', problem: 'Build multi-step automations without a separate tool' },
    ],
}

const PRODUCT_HEDGEHOG: Partial<Record<string, React.ComponentType<{ className?: string }>>> = {
    [ProductKey.PRODUCT_ANALYTICS]: GraphsHog,
    [ProductKey.WEB_ANALYTICS]: ExplorerHog,
    [ProductKey.SESSION_REPLAY]: FilmCameraHog,
    [ProductKey.LLM_ANALYTICS]: RobotHog,
    [ProductKey.DATA_WAREHOUSE]: BuilderHog1,
    [ProductKey.FEATURE_FLAGS]: FeatureFlagHog,
    [ProductKey.EXPERIMENTS]: ExperimentsHog,
    [ProductKey.ERROR_TRACKING]: DetectiveHog,
    [ProductKey.SURVEYS]: MicrophoneHog,
    [ProductKey.WORKFLOWS]: MailHog,
}

export function PostOnboardingModal(): JSX.Element | null {
    const { isModalOpen, productSetupConfig, onboardedProductKey } = useValues(postOnboardingModalLogic)
    const { ctaClicked, dismissModal } = useActions(postOnboardingModalLogic)

    const { trigger, HogfettiComponent } = useHogfetti(HOGFETTI_OPTIONS)

    const [ready, setReady] = useState(false)
    useEffect(() => {
        if (!isModalOpen) {
            setReady(false)
            return
        }
        const timer = setTimeout(() => setReady(true), 500)
        return () => clearTimeout(timer)
    }, [isModalOpen])

    useEffect(() => {
        if (!ready) {
            return
        }
        const run = async (): Promise<void> => {
            trigger()
            await new Promise((resolve) => setTimeout(resolve, 400))
            trigger()
            await new Promise((resolve) => setTimeout(resolve, 400))
            trigger()
        }
        void run()
    }, [ready, trigger])

    if (!ready) {
        return null
    }

    const HedgehogComponent = onboardedProductKey ? (PRODUCT_HEDGEHOG[onboardedProductKey] ?? SupermanHog) : SupermanHog
    const product = onboardedProductKey
        ? availableOnboardingProducts[onboardedProductKey as keyof typeof availableOnboardingProducts]
        : null
    const productColor = product?.iconColor ?? '#1D4AFF'
    const productName = product ? toSentenceCase(product.name) : 'PostHog'
    const valueProps = onboardedProductKey
        ? (PRODUCT_VALUE_PROPS[onboardedProductKey] ??
          // Fallback: derive from the product's capabilities if no custom value props defined
          (product?.capabilities ?? []).map((cap) => ({ title: cap, problem: '' })))
        : []
    const totalTasks = productSetupConfig?.tasks?.length ?? 0

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={() => dismissModal('close_button')}
            simple
            width={400}
            overlayClassName="!items-center"
            data-attr="post-onboarding-modal"
        >
            <HogfettiComponent />

            <div
                className="absolute inset-0 bg-gradient-to-b to-transparent pointer-events-none rounded-lg"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    backgroundImage: `linear-gradient(to bottom, ${productColor}10, ${productColor}04, transparent)`,
                }}
            />

            <div className="relative flex flex-col items-center gap-4 px-6 pt-8 pb-6 text-center">
                {/* Product hedgehog */}
                <div className="w-20 h-20 animate-float drop-shadow-md">
                    <HedgehogComponent className="w-full h-full object-contain" />
                </div>

                {/* Headline — promise, not status */}
                <div className="flex flex-col gap-1">
                    <h2 className="text-xl font-bold m-0 tracking-tight">You're ready to go</h2>
                    <p className="text-[13px] text-secondary m-0 leading-relaxed max-w-[300px]">
                        Your Quick Start guide will walk you through {productName} — here's what you'll unlock
                    </p>
                </div>

                {/* Value props — what you'll unlock + what problem it solves */}
                {valueProps.length > 0 && (
                    <div className="w-full flex flex-col gap-3 text-left">
                        {valueProps.map((vp) => (
                            <div key={vp.title} className="flex gap-2.5">
                                <IconCheckCircle
                                    className="w-[18px] h-[18px] shrink-0 mt-0.5"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ color: productColor }}
                                />
                                <div className="flex flex-col gap-0.5">
                                    <span className="text-[13px] font-medium text-primary">{vp.title}</span>
                                    {vp.problem && (
                                        <span className="text-xs text-secondary leading-snug">{vp.problem}</span>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                {/* Journey indicator — non-interactive, frames the scope */}
                <ProgressJourney totalTasks={totalTasks} productColor={productColor} />

                {/* Shortcuts */}
                <div className="flex items-center justify-center gap-4 text-[11px] text-muted">
                    <span className="inline-flex items-center gap-1">
                        <KeyboardShortcut command k />
                        <span>Search</span>
                    </span>
                    <span className="inline-flex items-center gap-1">
                        <span className="inline-flex items-center gap-0.5">
                            <KeyboardShortcut g preserveOrder />
                            <KeyboardShortcut s preserveOrder />
                        </span>
                        <span>Quick Start</span>
                    </span>
                    <span className="inline-flex items-center gap-1">
                        <kbd className="KeyboardShortcut">?</kbd>
                        <span>Shortcuts</span>
                    </span>
                </div>

                {/* CTA */}
                <LemonButton
                    type="primary"
                    fullWidth
                    center
                    onClick={() => ctaClicked()}
                    data-attr="post-onboarding-modal-cta"
                    sideIcon={<IconArrowRight />}
                >
                    Let's get started
                </LemonButton>

                <button
                    type="button"
                    onClick={() => dismissModal('explore_on_my_own')}
                    className="text-xs text-muted hover:text-primary transition-colors cursor-pointer bg-transparent border-none p-0"
                    data-attr="post-onboarding-modal-dismiss"
                >
                    I'll explore on my own
                </button>
            </div>
        </LemonModal>
    )
}

/** Animated progress bar that fills from 0 → 8% on mount to create a sense of momentum. */
function ProgressJourney({ totalTasks, productColor }: { totalTasks: number; productColor: string }): JSX.Element {
    const [width, setWidth] = useState(0)

    useEffect(() => {
        // Start at 0, animate to ~8% after a beat
        const timer = setTimeout(() => setWidth(8), 300)
        return () => clearTimeout(timer)
    }, [])

    return (
        <div className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border border-border bg-[var(--bg-light)]/40">
            <div className="flex-1">
                <div className="h-1.5 bg-border rounded-full overflow-hidden relative">
                    {/* Filled portion */}
                    <div
                        className="h-full rounded-full transition-all duration-1000 ease-out relative overflow-hidden"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${width}%`, backgroundColor: productColor }}
                    />
                    {/* Shimmer overlay that sweeps across the full track */}
                    <div
                        className="absolute inset-0 rounded-full"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            backgroundImage: `linear-gradient(90deg, transparent 0%, ${productColor}30 50%, transparent 100%)`,
                            backgroundSize: '40% 100%',
                            animation: 'progress-shimmer 2.5s ease-in-out infinite',
                        }}
                    />
                </div>
            </div>
            <span className="text-xs text-muted shrink-0 tabular-nums">{totalTasks} steps</span>
            {/* Inline keyframes for the shimmer */}
            <style>{`
                @keyframes progress-shimmer {
                    0% { background-position: -40% 0; }
                    100% { background-position: 140% 0; }
                }
            `}</style>
        </div>
    )
}
