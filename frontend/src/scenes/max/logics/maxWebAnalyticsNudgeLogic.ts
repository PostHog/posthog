import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { recentItemsModel } from '~/models/recentItemsModel'
import { HumanMessage } from '~/queries/schema/schema-assistant-messages'
import { ConversationTopic } from '~/types'

import { maxGlobalLogic } from '../maxGlobalLogic'
import type { ThreadMessage } from '../maxThreadLogic'
import { isHumanMessage } from '../utils'
import { isWebAnalyticsRelatedMessage, isWebAnalyticsRelatedQuestion } from '../utils/detectWebAnalyticsQuery'
import type { maxWebAnalyticsNudgeLogicType } from './maxWebAnalyticsNudgeLogicType'
import { maxWebAnalyticsNudgeSessionLogic } from './maxWebAnalyticsNudgeSessionLogic'

const WEB_ANALYTICS_RECENT_DAYS = 30

const WEB_ANALYTICS_SCENE_REFS: string[] = [
    Scene.WebAnalytics,
    Scene.WebAnalyticsPageReports,
    Scene.WebAnalyticsWebVitals,
    Scene.WebAnalyticsHealth,
    Scene.WebAnalyticsLive,
    Scene.MarketingAnalytics,
]

function getFinalAnswerGroup(messages: ThreadMessage[]): ThreadMessage[] {
    const group: ThreadMessage[] = []
    for (let i = messages.length - 1; i >= 0; i--) {
        if (isHumanMessage(messages[i])) {
            break
        }
        group.unshift(messages[i])
    }
    return group
}

export type NudgeTrigger = 'topic' | 'chart' | 'question'

export interface MaxWebAnalyticsNudgeLogicProps {
    messageId: string
    threadGrouped: ThreadMessage[]
    isCompleted: boolean
    isSharedThread: boolean
    conversationId: string | null
    // Domain classified by PostHog AI (from the conversation's first question); authoritative when present.
    conversationTopic: ConversationTopic | null
}

export interface NudgeReportProperties {
    conversation_id: string | null
    message_id: string
    variant: string | null
    trigger: NudgeTrigger
}

export const maxWebAnalyticsNudgeLogic = kea<maxWebAnalyticsNudgeLogicType>([
    path(['scenes', 'max', 'logics', 'maxWebAnalyticsNudgeLogic']),
    props({} as MaxWebAnalyticsNudgeLogicProps),
    key((props) => props.messageId),

    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            recentItemsModel,
            ['sceneLogViewsByRef', 'sceneLogViewsHasLoaded'],
            maxWebAnalyticsNudgeSessionLogic,
            ['shownForMessageId', 'dismissedThisSession', 'eligibleReportedThisSession'],
        ],
        actions: [maxWebAnalyticsNudgeSessionLogic, ['markNudgeShown', 'markNudgeDismissed', 'markEligibleReported']],
    })),

    actions({
        nudgeClicked: true,
        nudgeDismissed: true,
        evaluateReporting: true,
    }),

    selectors({
        variant: [
            (s) => [s.featureFlags],
            (featureFlags): string | null => {
                const value = featureFlags[FEATURE_FLAGS.MAX_WEB_ANALYTICS_NUDGE]
                return typeof value === 'string' ? value : null
            },
        ],
        finalAnswerGroup: [
            (_s, p) => [p.threadGrouped],
            (threadGrouped: ThreadMessage[]): ThreadMessage[] => getFinalAnswerGroup(threadGrouped),
        ],
        lastHumanQuestion: [
            (_s, p) => [p.threadGrouped],
            (threadGrouped: ThreadMessage[]): string | null =>
                (threadGrouped.filter(isHumanMessage).pop() as HumanMessage | undefined)?.content ?? null,
        ],
        groupHasWebChart: [
            (s) => [s.finalAnswerGroup],
            (finalAnswerGroup: ThreadMessage[]): boolean => finalAnswerGroup.some(isWebAnalyticsRelatedMessage),
        ],
        topicIsWebAnalytics: [
            (_s, p) => [p.conversationTopic],
            (conversationTopic: ConversationTopic | null): boolean => conversationTopic === 'web_analytics',
        ],
        trigger: [
            (s) => [s.topicIsWebAnalytics, s.groupHasWebChart],
            (topicIsWebAnalytics: boolean, groupHasWebChart: boolean): NudgeTrigger =>
                topicIsWebAnalytics ? 'topic' : groupHasWebChart ? 'chart' : 'question',
        ],
        isWebAnalyticsAnswer: [
            (s) => [s.topicIsWebAnalytics, s.groupHasWebChart, s.lastHumanQuestion],
            (topicIsWebAnalytics: boolean, groupHasWebChart: boolean, lastHumanQuestion: string | null): boolean =>
                topicIsWebAnalytics || groupHasWebChart || isWebAnalyticsRelatedQuestion(lastHumanQuestion),
        ],
        visitedWebAnalyticsRecently: [
            (s) => [s.sceneLogViewsByRef],
            (sceneLogViewsByRef: Record<string, string>): boolean => {
                const cutoff = dayjs().subtract(WEB_ANALYTICS_RECENT_DAYS, 'days')
                return WEB_ANALYTICS_SCENE_REFS.some((ref) => {
                    const viewedAt = sceneLogViewsByRef[ref]
                    return !!viewedAt && dayjs(viewedAt).isAfter(cutoff)
                })
            },
        ],
        isEligible: [
            (s, p) => [
                s.isWebAnalyticsAnswer,
                s.visitedWebAnalyticsRecently,
                s.sceneLogViewsHasLoaded,
                p.isCompleted,
                p.isSharedThread,
            ],
            (
                isWebAnalyticsAnswer: boolean,
                visitedRecently: boolean,
                sceneLogViewsHasLoaded: boolean,
                isCompleted: boolean,
                isSharedThread: boolean
            ): boolean =>
                isWebAnalyticsAnswer && !visitedRecently && sceneLogViewsHasLoaded && isCompleted && !isSharedThread,
        ],
        shouldShowNudge: [
            (s, p) => [s.isEligible, s.variant, s.dismissedThisSession, s.shownForMessageId, p.messageId],
            (
                isEligible: boolean,
                variant: string | null,
                dismissed: boolean,
                shownForMessageId: string | null,
                messageId: string
            ): boolean =>
                isEligible &&
                variant === 'test' &&
                !dismissed &&
                (shownForMessageId === null || shownForMessageId === messageId),
        ],
        reportProperties: [
            (s, p) => [s.variant, s.trigger, p.conversationId, p.messageId],
            (
                variant: string | null,
                trigger: NudgeTrigger,
                conversationId: string | null,
                messageId: string
            ): NudgeReportProperties => ({
                conversation_id: conversationId,
                message_id: messageId,
                variant,
                trigger,
            }),
        ],
    }),

    listeners(({ props, values, actions }) => ({
        nudgeClicked: () => {
            posthog.capture('posthog ai web analytics nudge clicked', values.reportProperties)
            // Move the chat into the side panel so it survives navigating away to web analytics.
            maxGlobalLogic.findMounted()?.actions.openSidePanelMax(props.conversationId ?? undefined)
            router.actions.push(urls.webAnalytics(), { utm_source: 'posthog-ai-nudge' })
        },
        nudgeDismissed: () => {
            posthog.capture('posthog ai web analytics nudge dismissed', values.reportProperties)
            actions.markNudgeDismissed()
        },
        evaluateReporting: () => {
            if (
                values.isEligible &&
                !values.eligibleReportedThisSession &&
                (values.variant === 'control' || values.variant === 'test')
            ) {
                actions.markEligibleReported()
                posthog.capture('posthog ai web analytics nudge eligible', values.reportProperties)
            }
            if (values.shouldShowNudge && values.shownForMessageId === null) {
                actions.markNudgeShown(props.messageId)
                posthog.capture('posthog ai web analytics nudge shown', values.reportProperties)
            }
        },
    })),

    subscriptions(({ actions }) => ({
        isEligible: () => actions.evaluateReporting(),
        shouldShowNudge: () => actions.evaluateReporting(),
    })),

    afterMount(({ actions }) => {
        actions.evaluateReporting()
    }),
])
