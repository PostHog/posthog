import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconArrowUpRight, IconLaptop, IconShare } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../../OnboardingStep'
import { useInstallationComplete } from '../hooks/useInstallationComplete'
import { RealtimeCheckIndicator } from '../RealtimeCheckIndicator'

interface MobileInstallHandoffProps {
    listeningForName: string
    teamPropertyToVerify: string
    header?: React.ReactNode
    onContinueHere: () => void
}

/**
 * Mobile install handoff — rendered in place of the regular install step for
 * users on a phone when the ONBOARDING_MOBILE_INSTALL_HELPER feature flag is
 * in the `test` arm.
 *
 * Data context (see research behind feat/onb-mobile-install):
 *   - ~4% of onboarding starters are on mobile (~2,000/month).
 *   - Mobile starters complete the install step at 19% vs 30.5% on desktop.
 *   - 80% of mobile starters who DO complete switch to a desktop first, and
 *     the median time between mobile start and desktop completion is 3.4h.
 *
 * This screen turns that "switch to desktop later" mechanic into an explicit
 * affordance: a Web Share API button that lets the user hand the install URL
 * off to their own email / AirDrop / Messages / Slack / whatever the OS share
 * sheet offers. A "Continue here anyway" escape hatch covers iOS/Android SDK
 * users who legitimately do want to install on their phone.
 *
 * The normal realtime install detection (useInstallationComplete) still runs,
 * so if the user actually opens the shared link on their computer and runs
 * the wizard there, events start flowing and this same page flips to a
 * "you're all set" state on their phone.
 */
export function MobileInstallHandoff({
    listeningForName,
    teamPropertyToVerify,
    header,
    onContinueHere,
}: MobileInstallHandoffProps): JSX.Element {
    const installationComplete = useInstallationComplete(teamPropertyToVerify)
    const [canShare, setCanShare] = useState(false)
    const [shareState, setShareState] = useState<'idle' | 'sent'>('idle')

    // Feature-detect Web Share API. Runs once on mount because `navigator` is
    // only defined on the client.
    useEffect(() => {
        setCanShare(typeof navigator !== 'undefined' && typeof navigator.share === 'function')
    }, [])

    // Fire a one-shot "shown" event on mount. product_key is pulled out of
    // the URL path so we can slice the experiment by which product the user
    // was trying to install (matches the data analysis methodology).
    useEffect(() => {
        const product = extractProductFromUrl()
        posthog.capture('mobile install handoff shown', { product_key: product })
    }, [])

    const handleShare = async (): Promise<void> => {
        const url = new URL(window.location.href)
        url.searchParams.set('source', 'mobile_handoff')
        const shareUrl = url.toString()

        posthog.capture('mobile install handoff clicked', { method: 'native_share' })

        try {
            await navigator.share({
                title: 'Finish setting up PostHog',
                text: "Here's where I left off setting up PostHog. Open this on your computer to continue.",
                url: shareUrl,
            })
            posthog.capture('mobile install handoff share completed')
            setShareState('sent')
        } catch {
            // User cancelled the share sheet, or a transient browser error.
            // Not an error case — they can try again or pick a different action.
            posthog.capture('mobile install handoff share cancelled')
        }
    }

    const handleContinueHere = (): void => {
        posthog.capture('mobile install handoff clicked', { method: 'continue_here' })
        onContinueHere()
    }

    return (
        <OnboardingStep
            title="Install"
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={!installationComplete ? 'Installation is not complete' : undefined}
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
                <div className="size-14 mx-auto rounded-full bg-primary-highlight flex items-center justify-center">
                    <IconLaptop className="size-7 text-primary" />
                </div>

                {installationComplete ? (
                    // If events started flowing in from the user's desktop while
                    // this page was open on their phone, flip to a "done" state.
                    <>
                        <h2 className="text-xl font-bold">You&apos;re all set</h2>
                        <p className="text-muted">
                            PostHog is receiving events from your project. You can continue onboarding here or on your
                            computer — whichever you prefer.
                        </p>
                    </>
                ) : (
                    <>
                        <h2 className="text-xl font-bold">
                            You&apos;re on a phone — want to finish this on your computer?
                        </h2>
                        <p className="text-muted">
                            The PostHog wizard runs a command in your project&apos;s root directory, so you&apos;ll need
                            to be on a computer with your code. We can send the link to you so you can pick up where you
                            left off.
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
                                    {shareState === 'sent' ? 'Send again' : 'Send link to my computer'}
                                </LemonButton>
                            ) : (
                                // Browsers without Web Share API (rare on mobile) fall back
                                // to copying the link so the user can paste it into any
                                // chat/email app themselves.
                                <LemonButton
                                    type="primary"
                                    size="large"
                                    icon={<IconArrowUpRight />}
                                    onClick={async () => {
                                        const url = new URL(window.location.href)
                                        url.searchParams.set('source', 'mobile_handoff')
                                        await navigator.clipboard.writeText(url.toString())
                                        posthog.capture('mobile install handoff clicked', {
                                            method: 'copy_link',
                                        })
                                        setShareState('sent')
                                    }}
                                    fullWidth
                                    data-attr="mobile-install-handoff-copy"
                                >
                                    {shareState === 'sent' ? 'Copied!' : 'Copy link to send to yourself'}
                                </LemonButton>
                            )}

                            {shareState === 'sent' && (
                                <p className="text-xs text-muted">
                                    Open the link on your computer and we&apos;ll pick up right where you are.
                                </p>
                            )}

                            <LemonButton
                                type="tertiary"
                                size="small"
                                onClick={handleContinueHere}
                                fullWidth
                                data-attr="mobile-install-handoff-continue-here"
                            >
                                Continue here anyway
                            </LemonButton>
                        </div>
                    </>
                )}
            </div>
        </OnboardingStep>
    )
}

// Pulls the onboarding product key out of the URL path — e.g.
// /project/123/onboarding/llm_analytics?step=install → "llm_analytics".
function extractProductFromUrl(): string | null {
    if (typeof window === 'undefined') {
        return null
    }
    const match = window.location.pathname.match(/\/onboarding\/([^/?]+)/)
    return match ? match[1] : null
}
