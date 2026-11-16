import { useActions, useValues } from 'kea'

import { IconInfo, IconX } from '@posthog/icons'
import { Badge, Button, Item, ItemActions, ItemContent, ItemMedia, Text } from '@posthog/quill'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import {
    SELF_LEARNING_DISMISS_KEY,
    feedbackBannerContent,
    selfLearningBannerAvailable,
    showSelfLearningBanner,
} from './supportTicketsBannerContent'
import { supportTicketsBannerLogic } from './supportTicketsBannerLogic'

interface QuillSupportTicketsBannerProps {
    aiEnabled: boolean
}

export function QuillSupportTicketsBanner({ aiEnabled }: QuillSupportTicketsBannerProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    // The settings endpoint is flag-gated, so its logic mounts only when the flags are on.
    return selfLearningBannerAvailable(featureFlags) ? (
        <SelfLearningOrFeedbackBanner aiEnabled={aiEnabled} />
    ) : (
        <FeedbackBanner aiEnabled={aiEnabled} />
    )
}

function SelfLearningOrFeedbackBanner({ aiEnabled }: QuillSupportTicketsBannerProps): JSX.Element | null {
    const { settings, settingsLoading } = useValues(supportTicketsBannerLogic)
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: SELF_LEARNING_DISMISS_KEY }))
    const { dismiss } = useActions(lemonBannerLogic({ dismissKey: SELF_LEARNING_DISMISS_KEY }))

    // Wait for the first load, so the feedback banner does not flash before the self-learning one.
    if (!settings && settingsLoading) {
        return null
    }
    if (!showSelfLearningBanner(settings, isDismissed)) {
        return <FeedbackBanner aiEnabled={aiEnabled} />
    }

    return (
        <Item variant="outline" size="sm" tone="info" className="flex-wrap">
            <ItemMedia variant="icon" aria-hidden>
                <IconInfo />
            </ItemMedia>
            <ItemContent className="min-w-0 gap-1">
                <Text size="xs" weight="semibold" render={<p className="m-0 flex flex-wrap items-center gap-1" />}>
                    Teach the AI agent from your resolved tickets
                    <Badge variant="info">Beta</Badge>
                </Text>
                <Text size="xs" render={<p className="m-0" />}>
                    <Button variant="link" size="inline" render={<LinkPrimitive to={urls.businessKnowledge()} />}>
                        Business knowledge
                    </Button>{' '}
                    is the set of docs, links, and notes the AI agent uses to answer tickets. With self-learning on,
                    PostHog adds reusable answers from your team's public replies on resolved tickets, so the agent can
                    answer more questions. You can review and edit everything it learns.
                </Text>
            </ItemContent>
            <ItemActions>
                <Button
                    variant="outline"
                    render={
                        <LinkPrimitive
                            to={`${urls.supportSettings()}#selectedSetting=conversations-learn-from-support`}
                        />
                    }
                    data-attr="support-self-learning-banner-turn-on"
                >
                    Turn on
                </Button>
                <Button size="icon" aria-label="Close" tooltip="Close" onClick={dismiss}>
                    <IconX />
                </Button>
            </ItemActions>
        </Item>
    )
}

function FeedbackBanner({ aiEnabled }: QuillSupportTicketsBannerProps): JSX.Element | null {
    const { dismissKey, buttonId, text } = feedbackBannerContent(aiEnabled)
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey }))
    const { dismiss } = useActions(lemonBannerLogic({ dismissKey }))

    if (isDismissed) {
        return null
    }

    return (
        <Item variant="outline" size="sm" tone="info" className="flex-wrap">
            <ItemMedia variant="icon" aria-hidden>
                <IconInfo />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <Text size="xs" render={<p className="m-0" />}>
                    {text}
                </Text>
            </ItemContent>
            <ItemActions>
                <Button variant="outline" id={buttonId}>
                    Send feedback
                </Button>
                <Button size="icon" aria-label="Close" tooltip="Close" onClick={dismiss}>
                    <IconX />
                </Button>
            </ItemActions>
        </Item>
    )
}
