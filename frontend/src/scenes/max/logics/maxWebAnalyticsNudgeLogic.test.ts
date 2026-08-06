import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { recentItemsModel } from '~/models/recentItemsModel'
import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { ThreadMessage } from '../maxThreadLogic'
import { maxWebAnalyticsNudgeLogic, MaxWebAnalyticsNudgeLogicProps } from './maxWebAnalyticsNudgeLogic'
import { maxWebAnalyticsNudgeSessionLogic } from './maxWebAnalyticsNudgeSessionLogic'

const WEB_CHART_MESSAGE: ThreadMessage = {
    type: AssistantMessageType.Artifact,
    content: {
        content_type: 'visualization',
        query: {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        },
    },
} as any

const NON_WEB_MESSAGE: ThreadMessage = {
    type: AssistantMessageType.Assistant,
    content: 'hi',
} as any

function humanMessage(content: string): ThreadMessage {
    return { type: AssistantMessageType.Human, content } as any
}

function buildProps(overrides: Partial<MaxWebAnalyticsNudgeLogicProps> = {}): MaxWebAnalyticsNudgeLogicProps {
    return {
        messageId: 'msg-1',
        threadGrouped: [WEB_CHART_MESSAGE],
        isCompleted: true,
        isSharedThread: false,
        conversationId: 'conv-1',
        conversationTopic: null,
        ...overrides,
    }
}

function setFlagVariant(variant: string): void {
    featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MAX_WEB_ANALYTICS_NUDGE]: variant })
}

function setFlagAbsent(): void {
    featureFlagLogic.actions.setFeatureFlags([], {})
}

function setRecentVisit(scene: string, daysAgo: number): void {
    recentItemsModel.actions.loadSceneLogViewsSuccess({ [scene]: dayjs().subtract(daysAgo, 'days').toISOString() })
}

function setNoRecentVisit(): void {
    recentItemsModel.actions.loadSceneLogViewsSuccess({})
}

describe('maxWebAnalyticsNudgeLogic', () => {
    let logic: ReturnType<typeof maxWebAnalyticsNudgeLogic.build>

    beforeEach(() => {
        initKeaTests()
        window.sessionStorage.clear()

        jest.spyOn(api.fileSystemLogView, 'list').mockReturnValue(new Promise(() => undefined))
        jest.spyOn(api.fileSystem, 'list').mockReturnValue(new Promise(() => undefined))

        featureFlagLogic.mount()
        maxWebAnalyticsNudgeSessionLogic.mount()
        recentItemsModel.mount()
    })

    afterEach(() => {
        logic?.unmount()
        maxWebAnalyticsNudgeSessionLogic.unmount()
        recentItemsModel.unmount()
        featureFlagLogic.unmount()
        window.sessionStorage.clear()
        jest.restoreAllMocks()
    })

    describe('visitedWebAnalyticsRecently', () => {
        it.each([
            ['WebAnalytics visited 5 days ago', Scene.WebAnalytics, 5, true],
            ['WebAnalytics visited 40 days ago', Scene.WebAnalytics, 40, false],
            ['MarketingAnalytics visited 5 days ago', Scene.MarketingAnalytics, 5, true],
        ])('%s returns %s', (_label, scene, daysAgo, expected) => {
            setRecentVisit(scene as string, daysAgo)
            setFlagVariant('test')
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()
            expect(logic.values.visitedWebAnalyticsRecently).toBe(expected)
        })

        it('returns false when no scene views are recorded', () => {
            setNoRecentVisit()
            setFlagVariant('test')
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()
            expect(logic.values.visitedWebAnalyticsRecently).toBe(false)
        })
    })

    describe('isWebAnalyticsAnswer', () => {
        beforeEach(() => {
            setNoRecentVisit()
            setFlagVariant('test')
        })

        it('returns true for a web analytics chart message', () => {
            logic = maxWebAnalyticsNudgeLogic(buildProps({ threadGrouped: [WEB_CHART_MESSAGE] }))
            logic.mount()
            expect(logic.values.isWebAnalyticsAnswer).toBe(true)
        })

        it('returns true when the chart is not the last message in the group (chart + trailing summary text)', () => {
            logic = maxWebAnalyticsNudgeLogic(buildProps({ threadGrouped: [WEB_CHART_MESSAGE, NON_WEB_MESSAGE] }))
            logic.mount()
            expect(logic.values.isWebAnalyticsAnswer).toBe(true)
            expect(logic.values.trigger).toBe('chart')
        })

        it('returns true when group is non-web but question text is web analytics related', () => {
            logic = maxWebAnalyticsNudgeLogic(
                buildProps({ threadGrouped: [humanMessage('where is my traffic coming from?'), NON_WEB_MESSAGE] })
            )
            logic.mount()
            expect(logic.values.isWebAnalyticsAnswer).toBe(true)
        })

        it('returns true for a "visited my website" question with no chart signals', () => {
            logic = maxWebAnalyticsNudgeLogic(
                buildProps({
                    threadGrouped: [humanMessage('How many people visited my website last week?'), NON_WEB_MESSAGE],
                })
            )
            logic.mount()
            expect(logic.values.isWebAnalyticsAnswer).toBe(true)
        })

        it('returns false when group is non-web and question text has no web keywords', () => {
            logic = maxWebAnalyticsNudgeLogic(
                buildProps({ threadGrouped: [humanMessage('how many users signed up?'), NON_WEB_MESSAGE] })
            )
            logic.mount()
            expect(logic.values.isWebAnalyticsAnswer).toBe(false)
        })

        it('returns true when the conversation topic is web_analytics, even with a non-web group and question', () => {
            logic = maxWebAnalyticsNudgeLogic(
                buildProps({
                    threadGrouped: [humanMessage('how many users signed up?'), NON_WEB_MESSAGE],
                    conversationTopic: 'web_analytics',
                })
            )
            logic.mount()
            expect(logic.values.isWebAnalyticsAnswer).toBe(true)
        })

        it('a non-web conversation topic does not by itself make it a web analytics answer', () => {
            logic = maxWebAnalyticsNudgeLogic(
                buildProps({
                    threadGrouped: [humanMessage('how many users signed up?'), NON_WEB_MESSAGE],
                    conversationTopic: 'product_analytics',
                })
            )
            logic.mount()
            expect(logic.values.isWebAnalyticsAnswer).toBe(false)
        })
    })

    describe('trigger', () => {
        beforeEach(() => {
            setNoRecentVisit()
            setFlagVariant('test')
        })

        it('returns "chart" for a web analytics chart message', () => {
            logic = maxWebAnalyticsNudgeLogic(buildProps({ threadGrouped: [WEB_CHART_MESSAGE] }))
            logic.mount()
            expect(logic.values.trigger).toBe('chart')
        })

        it('returns "question" when only the question text matched (non-web group + web question)', () => {
            logic = maxWebAnalyticsNudgeLogic(
                buildProps({ threadGrouped: [humanMessage('show me my top pages'), NON_WEB_MESSAGE] })
            )
            logic.mount()
            expect(logic.values.trigger).toBe('question')
        })

        it('returns "topic" when the conversation topic is web_analytics (authoritative over chart)', () => {
            logic = maxWebAnalyticsNudgeLogic(
                buildProps({ threadGrouped: [WEB_CHART_MESSAGE], conversationTopic: 'web_analytics' })
            )
            logic.mount()
            expect(logic.values.trigger).toBe('topic')
        })
    })

    describe('isEligible', () => {
        beforeEach(() => {
            setNoRecentVisit()
            setFlagVariant('test')
        })

        it('is true when all conditions hold', () => {
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()
            expect(logic.values.isEligible).toBe(true)
        })

        it.each([
            ['isCompleted is false', { isCompleted: false }],
            ['isSharedThread is true', { isSharedThread: true }],
        ] as [string, Partial<MaxWebAnalyticsNudgeLogicProps>][])('is false when %s', (_label, propsOverride) => {
            logic = maxWebAnalyticsNudgeLogic(buildProps(propsOverride))
            logic.mount()
            expect(logic.values.isEligible).toBe(false)
        })

        it('is false when visitedWebAnalyticsRecently is true', () => {
            setRecentVisit(Scene.WebAnalytics, 5)
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()
            expect(logic.values.isEligible).toBe(false)
        })
    })

    describe('isEligible when sceneLogViewsHasLoaded is false', () => {
        it('is false when sceneLogViewsHasLoaded is false', () => {
            setFlagVariant('test')

            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()

            expect(logic.values.sceneLogViewsHasLoaded).toBe(false)
            expect(logic.values.isEligible).toBe(false)
        })
    })

    describe('shouldShowNudge', () => {
        beforeEach(() => {
            setNoRecentVisit()
        })

        it('is true when variant is "test", eligible, and fresh session', () => {
            setFlagVariant('test')
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()
            expect(logic.values.shouldShowNudge).toBe(true)
        })

        it('is false when variant is "control"', () => {
            setFlagVariant('control')
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()
            expect(logic.values.shouldShowNudge).toBe(false)
        })

        it('is false when flag is not enrolled', () => {
            setFlagAbsent()
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()
            expect(logic.values.shouldShowNudge).toBe(false)
        })

        it('is false after nudgeDismissed', async () => {
            setFlagVariant('test')
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.nudgeDismissed()
            }).toMatchValues({ shouldShowNudge: false })
        })

        it('is false when shownForMessageId already equals a DIFFERENT message id', () => {
            maxWebAnalyticsNudgeSessionLogic.actions.hydrateFromStorage({
                shownForMessageId: 'other-msg',
                dismissed: false,
                eligibleReported: false,
            })

            setFlagVariant('test')
            logic = maxWebAnalyticsNudgeLogic(buildProps({ messageId: 'msg-1' }))
            logic.mount()
            expect(logic.values.shouldShowNudge).toBe(false)
        })

        it('is true when shownForMessageId equals this message id', () => {
            maxWebAnalyticsNudgeSessionLogic.actions.hydrateFromStorage({
                shownForMessageId: 'msg-1',
                dismissed: false,
                eligibleReported: false,
            })

            setFlagVariant('test')
            logic = maxWebAnalyticsNudgeLogic(buildProps({ messageId: 'msg-1' }))
            logic.mount()
            expect(logic.values.shouldShowNudge).toBe(true)
        })
    })

    describe('posthog.capture reporting', () => {
        let captureSpy: jest.SpyInstance

        beforeEach(() => {
            captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            setNoRecentVisit()
        })

        afterEach(() => {
            captureSpy.mockRestore()
        })

        it('fires both "eligible" and "shown" exactly once for variant "test" on mount', () => {
            setFlagVariant('test')
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()

            const expectedProperties = {
                conversation_id: 'conv-1',
                message_id: 'msg-1',
                variant: 'test',
                trigger: 'chart',
            }
            expect(captureSpy).toHaveBeenCalledWith('posthog ai web analytics nudge eligible', expectedProperties)
            expect(captureSpy).toHaveBeenCalledWith('posthog ai web analytics nudge shown', expectedProperties)
            expect(
                captureSpy.mock.calls.filter((c) => c[0] === 'posthog ai web analytics nudge eligible')
            ).toHaveLength(1)
            expect(captureSpy.mock.calls.filter((c) => c[0] === 'posthog ai web analytics nudge shown')).toHaveLength(1)
        })

        it('fires "eligible" only (no "shown") for variant "control"', () => {
            setFlagVariant('control')
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()

            expect(captureSpy).toHaveBeenCalledWith(
                'posthog ai web analytics nudge eligible',
                expect.objectContaining({ variant: 'control' })
            )
            expect(captureSpy).not.toHaveBeenCalledWith('posthog ai web analytics nudge shown', expect.anything())
        })

        it('fires neither event when not enrolled in the flag', () => {
            setFlagAbsent()
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()

            expect(captureSpy).not.toHaveBeenCalledWith('posthog ai web analytics nudge eligible', expect.anything())
            expect(captureSpy).not.toHaveBeenCalledWith('posthog ai web analytics nudge shown', expect.anything())
        })
    })

    describe('nudgeClicked and nudgeDismissed actions', () => {
        let captureSpy: jest.SpyInstance

        beforeEach(() => {
            captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            setNoRecentVisit()
            setFlagVariant('test')
            logic = maxWebAnalyticsNudgeLogic(buildProps())
            logic.mount()
            captureSpy.mockClear()
        })

        afterEach(() => {
            captureSpy.mockRestore()
        })

        it('nudgeClicked fires the clicked event with reportProperties', async () => {
            await expectLogic(logic, () => {
                logic.actions.nudgeClicked()
            })

            expect(captureSpy).toHaveBeenCalledWith('posthog ai web analytics nudge clicked', {
                conversation_id: 'conv-1',
                message_id: 'msg-1',
                variant: 'test',
                trigger: 'chart',
            })
        })

        it('nudgeClicked navigates to web analytics so the chat moves to the side panel', async () => {
            const pushSpy = jest.spyOn(router.actions, 'push')

            await expectLogic(logic, () => {
                logic.actions.nudgeClicked()
            })

            expect(pushSpy).toHaveBeenCalledWith(urls.webAnalytics(), { utm_source: 'posthog-ai-nudge' })
        })

        it('nudgeDismissed fires the dismissed event and flips shouldShowNudge to false', async () => {
            expect(logic.values.shouldShowNudge).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.nudgeDismissed()
            }).toMatchValues({ shouldShowNudge: false })

            expect(captureSpy).toHaveBeenCalledWith('posthog ai web analytics nudge dismissed', {
                conversation_id: 'conv-1',
                message_id: 'msg-1',
                variant: 'test',
                trigger: 'chart',
            })
        })
    })

    describe('once-per-session deduplication', () => {
        let captureSpy: jest.SpyInstance
        let logic2: ReturnType<typeof maxWebAnalyticsNudgeLogic.build>

        beforeEach(() => {
            captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            setNoRecentVisit()
            setFlagVariant('test')
        })

        afterEach(() => {
            logic2?.unmount()
            captureSpy.mockRestore()
        })

        it('does not fire eligible or shown again for a second message, and shouldShowNudge is false on it', async () => {
            logic = maxWebAnalyticsNudgeLogic(buildProps({ messageId: 'msg-1' }))
            logic.mount()

            const eligibleCalls1 = captureSpy.mock.calls.filter(
                (c) => c[0] === 'posthog ai web analytics nudge eligible'
            ).length
            const shownCalls1 = captureSpy.mock.calls.filter(
                (c) => c[0] === 'posthog ai web analytics nudge shown'
            ).length
            expect(eligibleCalls1).toBe(1)
            expect(shownCalls1).toBe(1)

            captureSpy.mockClear()

            logic2 = maxWebAnalyticsNudgeLogic(buildProps({ messageId: 'msg-2' }))
            logic2.mount()

            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(
                captureSpy.mock.calls.filter((c) => c[0] === 'posthog ai web analytics nudge eligible')
            ).toHaveLength(0)
            expect(captureSpy.mock.calls.filter((c) => c[0] === 'posthog ai web analytics nudge shown')).toHaveLength(0)

            expect(logic2.values.shouldShowNudge).toBe(false)
        })
    })
})
