import { useValues } from 'kea'
import posthog from 'posthog-js'
import { memo, useEffect, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { HedgehogActor, HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { FEATURE_FLAGS } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { inStorybook, inStorybookTestRunner, isMobile, sampleOne } from 'lib/utils'

import { HedgehogConfig, OnboardingStepKey } from '~/types'

import { onboardingLogic } from './onboardingLogic'

const ONBOARDING_HEDGEHOG_PHRASES: Record<OnboardingStepKey, string[]> = {
    [OnboardingStepKey.INSTALL]: [
        "Let's get you set up! 🚀",
        "I'm so excited to help you install PostHog!",
        'This is the fun part - adding some code!',
        "Don't worry, I'll guide you through this!",
        'Copy, paste, and we are off to the races!',
    ],
    [OnboardingStepKey.VERIFY]: [
        "Almost there! Let's verify it's working.",
        'Waiting for those sweet, sweet events...',
        'The anticipation is killing me! 🦔',
        "C'mon events, show yourselves!",
    ],
    [OnboardingStepKey.PRODUCT_CONFIGURATION]: [
        'Time to customize! Make it your own.',
        "Tweak these settings to your heart's content.",
        'Every team is different - set it up your way!',
        'These defaults are pretty good, but you know best!',
    ],
    [OnboardingStepKey.LINK_DATA]: [
        'Got data elsewhere? Bring it all together!',
        'The more data, the merrier! 📊',
        "Let's connect all your sources!",
    ],
    [OnboardingStepKey.PLANS]: [
        "Let's find the perfect plan for you!",
        'More features = more hedgehog happiness 🦔',
        'Pick what works best for your team.',
    ],
    [OnboardingStepKey.REVERSE_PROXY]: [
        'A reverse proxy helps with ad blockers!',
        'This step is optional but recommended.',
        'Pro tip: proxies make tracking more reliable!',
    ],
    [OnboardingStepKey.INVITE_TEAMMATES]: [
        'Data is better with friends! 🎉',
        "Invite your team - they'll thank you later!",
        'Collaboration makes insights better!',
        'The more the merrier!',
    ],
    [OnboardingStepKey.SESSION_REPLAY]: [
        'Watch your users in action! 🎬',
        'Session replays are like magic!',
        'See exactly what your users see.',
    ],
    [OnboardingStepKey.AUTHORIZED_DOMAINS]: [
        "Let's set up your authorized domains.",
        'This keeps your data secure!',
        'Only track what you want to track.',
    ],
    [OnboardingStepKey.SOURCE_MAPS]: [
        'Source maps make debugging a breeze!',
        'Turn cryptic errors into readable code.',
        'Your future self will thank you!',
    ],
    [OnboardingStepKey.ALERTS]: [
        'Get notified when things go wrong!',
        'Alerts = peace of mind 🧘',
        'Stay on top of issues before users notice.',
    ],
    [OnboardingStepKey.AI_CONSENT]: [
        'AI can supercharge your analytics!',
        'Max the AI hedgehog at your service! 🤖🦔',
        'Let me help you make sense of your data.',
    ],
    [OnboardingStepKey.TELL_US_MORE]: [
        'Tell me about yourself!',
        "I'd love to know more about your project.",
        'This helps us help you better!',
    ],
}

const DEFAULT_PHRASES = [
    "Hi! I'm Max, your friendly hedgehog guide! 🦔",
    "You can drag me around if you want, I'm friendly!",
    "You're doing great!",
    'Welcome to PostHog!',
]

const DISMISS_PHRASE = 'Bye bye!'

const PHRASE_DURATION = 5000 // Phrase is displayed for 5 seconds
const PHRASE_INTERVAL = 15000 // Phrase changes every 15 seconds

const ONBOARDING_HEDGEHOG_CONFIG: HedgehogConfig = {
    enabled: true,
    use_as_profile: false,
    color: null,
    accessories: [],
    walking_enabled: true,
    interactions_enabled: true,
    controls_enabled: false,
    party_mode_enabled: false,
}

const InnerOnboardingHedgehog = memo(function OnboardingHedgehog(): JSX.Element | null {
    const { stepKey } = useValues(onboardingLogic)
    const [isDismissed, setIsDismissed] = useState(false)
    const [actor, setActor] = useState<HedgehogActor | null>(null)
    const [currentPhrase, setCurrentPhrase] = useState<string>('')
    const [showSpeechBubble, setShowSpeechBubble] = useState(true)
    const { isVisible: isPageVisible } = usePageVisibility()

    const dismiss = (): void => {
        setCurrentPhrase(DISMISS_PHRASE)
        actor?.setAnimation('wave', {
            onComplete() {
                setIsDismissed(true)
            },
        })
    }

    useEffect(() => {
        let timeoutHandler: NodeJS.Timeout | null = null
        const setAndDismissPhrase = (): void => {
            setShowSpeechBubble(true)
            setCurrentPhrase((currentPhrase) => {
                const thisStepPhrases = ONBOARDING_HEDGEHOG_PHRASES[stepKey as OnboardingStepKey]
                const phrases = [...thisStepPhrases, ...thisStepPhrases, ...DEFAULT_PHRASES] // Display this step phrases twice as often

                const filteredPhrases = phrases.filter((phrase) => phrase !== currentPhrase)
                return sampleOne(filteredPhrases)
            })

            timeoutHandler = setTimeout(() => {
                setShowSpeechBubble(false)
            }, PHRASE_DURATION)
        }

        // Run immediately and then every `PHRASE_INTERVAL` seconds,
        // after the first `PHRASE_DURATION` seconds the phrase is removed
        setAndDismissPhrase()
        const handler = setInterval(setAndDismissPhrase, PHRASE_INTERVAL)

        return () => {
            clearInterval(handler)
            if (timeoutHandler) {
                clearTimeout(timeoutHandler)
            }
        }
    }, [stepKey])

    if (isDismissed) {
        return null
    }

    const speechBubbleContent = showSpeechBubble && currentPhrase && (
        <div className="flex items-start gap-2 p-2 w-80">
            <p className="text-sm m-0 flex-1">{currentPhrase}</p>
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                onClick={(e) => {
                    e.stopPropagation()
                    dismiss()
                    posthog.capture('onboarding hedgehog dismissed')
                }}
                tooltip="Dismiss Max for now"
            />
        </div>
    )

    return (
        <div className="hidden md:block">
            <HedgehogBuddy
                onActorLoaded={(actor) => setActor(actor)}
                onClick={(actor) => {
                    setCurrentPhrase(sampleOne(DEFAULT_PHRASES))
                    setShowSpeechBubble(true)
                    actor.setAnimation('wave')
                }}
                hedgehogConfig={ONBOARDING_HEDGEHOG_CONFIG}
                paused={!isPageVisible}
                tooltip={speechBubbleContent || undefined}
                tooltipAlwaysVisible={showSpeechBubble}
            />
        </div>
    )
})

export const OnboardingHedgehog = (): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)

    if (inStorybook() || inStorybookTestRunner()) {
        return null
    }

    if (isMobile()) {
        return null
    }

    if (featureFlags[FEATURE_FLAGS.ONBOARDING_HEDGEHOG_MODE] !== 'test') {
        return null
    }

    return <InnerOnboardingHedgehog />
}
