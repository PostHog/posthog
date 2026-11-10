import { useValues } from 'kea'

import { LemonBanner, LemonTag, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { supportTicketsBannerLogic } from './supportTicketsBannerLogic'

const SELF_LEARNING_DISMISS_KEY = 'support-self-learning-banner'

interface SupportTicketsBannerProps {
    aiEnabled: boolean
}

export function SupportTicketsBanner({ aiEnabled }: SupportTicketsBannerProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const selfLearningAvailable =
        !!featureFlags[FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE] &&
        !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_AI_SUGGESTION_ORGS]

    // The settings endpoint is flag-gated, so its logic mounts only when the flags are on.
    return selfLearningAvailable ? (
        <SelfLearningOrFeedbackBanner aiEnabled={aiEnabled} />
    ) : (
        <FeedbackBanner aiEnabled={aiEnabled} />
    )
}

function SelfLearningOrFeedbackBanner({ aiEnabled }: SupportTicketsBannerProps): JSX.Element | null {
    const { settings, settingsLoading } = useValues(supportTicketsBannerLogic)
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: SELF_LEARNING_DISMISS_KEY }))

    // Wait for the first load, so the feedback banner does not flash before the self-learning one.
    if (!settings && settingsLoading) {
        return null
    }

    const showSelfLearning =
        !isDismissed && !!settings && settings.support_enabled && !settings.learn_from_support_enabled
    if (!showSelfLearning) {
        return <FeedbackBanner aiEnabled={aiEnabled} />
    }

    return (
        <LemonBanner
            type="info"
            dismissKey={SELF_LEARNING_DISMISS_KEY}
            action={{
                children: 'Turn on',
                to: `${urls.supportSettings()}#selectedSetting=conversations-learn-from-support`,
                'data-attr': 'support-self-learning-banner-turn-on',
            }}
        >
            <p className="font-semibold mb-1 flex flex-wrap items-center gap-1">
                Teach the AI agent from your resolved tickets
                <LemonTag type="highlight" size="small">
                    Beta
                </LemonTag>
            </p>
            <p className="mb-0 font-normal">
                <Link to={urls.businessKnowledge()}>Business knowledge</Link> is the set of docs, links, and notes the
                AI agent uses to answer tickets. With self-learning on, PostHog adds reusable answers from your team's
                public replies on resolved tickets, so the agent can answer more questions. You can review and edit
                everything it learns.
            </p>
        </LemonBanner>
    )
}

function FeedbackBanner({ aiEnabled }: SupportTicketsBannerProps): JSX.Element {
    // pinned: survey 01a17c76-69b3-0000-bb24-4adfd734f406 targets #ai-support-feedback-button
    return aiEnabled ? (
        <LemonBanner
            type="info"
            dismissKey="ai-support-feedback-banner"
            action={{ children: 'Send feedback', id: 'ai-support-feedback-button' }}
        >
            <p>Tell us how the AI agent is working, or report any issues.</p>
        </LemonBanner>
    ) : (
        <LemonBanner
            type="info"
            dismissKey="support-feedback-banner"
            action={{ children: 'Send feedback', id: 'support-feedback-button' }}
        >
            <p>Tell us how the support product is working, or report any issues.</p>
        </LemonBanner>
    )
}
