import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import { IconArrowUpRight, IconLaptop, IconShare } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../../onboardingLogic'
import { OnboardingStep } from '../../OnboardingStep'
import { RealtimeCheckIndicator } from '../RealtimeCheckIndicator'

interface MobileInstallHandoffProps {
    listeningForName: string
    teamPropertyToVerify: string
    installationComplete: boolean
    header?: React.ReactNode
    onContinueHere: () => void
}

/**
 * Install step for mobile users in the ONBOARDING_MOBILE_INSTALL_HELPER `test`
 * arm. Offers to hand off the install URL to the user's computer via the Web
 * Share API, with a copy-link fallback and a "continue on this device" escape.
 * When events start arriving, the card flips to a success state with an
 * in-card continue button.
 */
export function MobileInstallHandoff({
    listeningForName,
    teamPropertyToVerify,
    installationComplete,
    header,
    onContinueHere,
}: MobileInstallHandoffProps): JSX.Element {
    const { productKey, hasNextStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep } = useActions(onboardingLogic)

    const canShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'
    const [shareState, setShareState] = useState<'idle' | 'sent'>('idle')
    const shownCapturedRef = useRef(false)

    useEffect(() => {
        if (shownCapturedRef.current) {
            return
        }
        shownCapturedRef.current = true
        posthog.capture('mobile install handoff shown', { product_key: productKey })
    }, [productKey])

    // Reset the "sent"/"copied" confirmation after a short delay so the button
    // label doesn't become a dead-end. Cleanup on unmount + on state change.
    useEffect(() => {
        if (shareState !== 'sent') {
            return
        }
        const timer = setTimeout(() => setShareState('idle'), 2500)
        return () => clearTimeout(timer)
    }, [shareState])

    // Build the handoff URL from known-safe segments only. We explicitly
    // whitelist which query params to forward — the existing `source`
    // attribution is preserved so cross-experiment attribution chains stay
    // intact, while arbitrary query params (debug flags, experiment
    // overrides) get dropped.
    const buildHandoffUrl = (): string => {
        const url = new URL(window.location.origin + window.location.pathname)
        url.searchParams.set('step', 'install')
        url.searchParams.set('handoff', 'mobile')
        const existingSource = new URLSearchParams(window.location.search).get('source')
        if (existingSource) {
            url.searchParams.set('source', existingSource)
        }
        return url.toString()
    }

    const handleShare = async (): Promise<void> => {
        posthog.capture('mobile install handoff clicked', { method: 'native_share' }, { send_instantly: true })

        try {
            await navigator.share({
                title: 'Finish setting up PostHog',
                text: "Here's where I left off setting up PostHog. Open this on your computer to continue.",
                url: buildHandoffUrl(),
            })
            posthog.capture('mobile install handoff share completed', {}, { send_instantly: true })
            setShareState('sent')
        } catch (err) {
            const name = err instanceof Error ? err.name : 'unknown'
            if (name === 'AbortError') {
                posthog.capture('mobile install handoff share cancelled', {}, { send_instantly: true })
                return
            }
            posthog.capture('mobile install handoff share failed', { error: name }, { send_instantly: true })
            // Real failure (not user cancellation) — fall back to copy so
            // the user still has a way to get the link off this device.
            // copyToClipboard shows its own toast for success/failure.
            // Don't re-capture 'clicked' — we already captured it above with method: 'native_share'.
            await handleCopy(false)
        }
    }

    const handleCopy = async (shouldCapture = true): Promise<void> => {
        const success = await copyToClipboard(buildHandoffUrl(), 'install link')
        if (success) {
            if (shouldCapture) {
                posthog.capture('mobile install handoff clicked', { method: 'copy_link' })
            }
            setShareState('sent')
        } else {
            posthog.capture('mobile install handoff copy failed')
        }
    }

    const handleContinueHere = (): void => {
        posthog.capture('mobile install handoff clicked', { method: 'continue_here' }, { send_instantly: true })
        onContinueHere()
    }

    const handleContinueOnboarding = (): void => {
        if (hasNextStep) {
            goToNextStep()
        } else {
            completeOnboarding()
        }
    }

    return (
        <OnboardingStep
            title="Install"
            stepKey={OnboardingStepKey.INSTALL}
            showContinue={false}
            showSkip={!installationComplete}
            actions={
                <div className="pr-2">
                    <RealtimeCheckIndicator
                        teamPropertyToVerify={teamPropertyToVerify}
                        listeningForName={listeningForName}
                    />
                </div>
            }
        >
            {header}
            <div className="mt-6 max-w-md mx-auto text-center space-y-4">
                <div
                    aria-hidden="true"
                    className="size-14 mx-auto rounded-full bg-primary-highlight flex items-center justify-center"
                >
                    <IconLaptop className="size-7 text-primary" />
                </div>

                {installationComplete ? (
                    <>
                        <h2 className="text-xl font-bold">You&apos;re all set</h2>
                        <p className="text-muted">
                            PostHog is receiving events from your project. You&apos;re ready to continue.
                        </p>
                        <div className="pt-2">
                            <LemonButton
                                type="primary"
                                size="large"
                                onClick={handleContinueOnboarding}
                                fullWidth
                                data-attr="mobile-install-handoff-continue-onboarding"
                            >
                                {hasNextStep ? 'Continue' : 'Finish'}
                            </LemonButton>
                        </div>
                    </>
                ) : (
                    <>
                        <h2 className="text-xl font-bold">Finish setting up on your computer?</h2>
                        <p className="text-muted">
                            PostHog&apos;s install command needs to run on a computer with your code. We can share the
                            link so you can continue there.
                        </p>

                        <div className="space-y-2 pt-2">
                            {canShare ? (
                                <LemonButton
                                    type="primary"
                                    size="large"
                                    icon={<IconShare />}
                                    onClick={handleShare}
                                    fullWidth
                                    data-attr="mobile-install-handoff-share"
                                >
                                    {shareState === 'sent' ? 'Share again' : 'Share link'}
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    type="primary"
                                    size="large"
                                    icon={<IconArrowUpRight />}
                                    onClick={() => handleCopy()}
                                    fullWidth
                                    data-attr="mobile-install-handoff-copy"
                                >
                                    {shareState === 'sent' ? 'Copied!' : 'Copy link'}
                                </LemonButton>
                            )}

                            {shareState === 'sent' && (
                                <p className="text-xs text-muted">
                                    Open the link on your computer and we&apos;ll pick up right where you left off.
                                </p>
                            )}

                            <LemonButton
                                type="tertiary"
                                size="small"
                                onClick={handleContinueHere}
                                fullWidth
                                data-attr="mobile-install-handoff-continue-here"
                            >
                                Continue on this device
                            </LemonButton>
                        </div>
                    </>
                )}
            </div>
        </OnboardingStep>
    )
}
