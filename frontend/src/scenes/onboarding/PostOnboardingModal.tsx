import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowRight, IconCheckCircle } from '@posthog/icons'

import { SupermanHog } from 'lib/components/hedgehogs'
import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { postOnboardingModalLogic } from './postOnboardingModalLogic'
import { availableOnboardingProducts, toSentenceCase } from './utils'

const HOGFETTI_OPTIONS = { count: 100, duration: 3000 }

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

    const product = onboardedProductKey
        ? availableOnboardingProducts[onboardedProductKey as keyof typeof availableOnboardingProducts]
        : null
    const HedgehogComponent = product?.hedgehog ?? SupermanHog
    const productColor = product?.iconColor ?? '#1D4AFF'
    const productName = product ? toSentenceCase(product.name) : 'PostHog'
    const valueProps = product?.valueProps ?? (product?.capabilities ?? []).map((cap) => ({ title: cap, problem: '' }))
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
