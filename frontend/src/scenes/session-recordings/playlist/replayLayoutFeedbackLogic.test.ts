import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { FeedbackPromptState, feedbackPromptDue, replayLayoutFeedbackLogic } from './replayLayoutFeedbackLogic'

jest.mock('lib/constants', () => ({
    ...jest.requireActual<typeof import('lib/constants')>('lib/constants'),
    REPLAY_LAYOUT_SWITCH_BACK_SURVEY_ID: 'switch-back-survey',
    REPLAY_LAYOUT_FEEDBACK_SURVEY_ID: 'feedback-survey',
}))

const DUE: FeedbackPromptState = {
    replayLayout: 'compact',
    canOverrideLayout: false,
    newLayoutVisitDays: 5,
    feedbackPromptShown: false,
    switchBackSurveyShown: false,
}

describe('replayLayoutFeedbackLogic', () => {
    let logic: ReturnType<typeof replayLayoutFeedbackLogic.build>
    let displaySurvey: jest.SpyInstance
    let capture: jest.SpyInstance

    function setArm(arm: string): void {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.REPLAY_WATCH_LAYOUT], {
            [FEATURE_FLAGS.REPLAY_WATCH_LAYOUT]: arm,
        })
    }

    function openOn(day: string): void {
        jest.setSystemTime(new Date(`${day}T12:00:00`))
        logic.actions.replayPageOpened()
    }

    beforeEach(() => {
        jest.useFakeTimers()
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
        posthog.register_for_session = jest.fn()
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        displaySurvey = jest.spyOn(posthog, 'displaySurvey').mockImplementation(() => undefined)
        jest.spyOn(posthog, 'getSurveys').mockImplementation((callback) =>
            callback([{ id: 'switch-back-survey' }, { id: 'feedback-survey' }] as any)
        )
        logic = replayLayoutFeedbackLogic()
        logic.mount()
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each([
        { name: 'due on the fifth day', state: DUE, expected: true },
        { name: 'not due before the fifth day', state: { ...DUE, newLayoutVisitDays: 4 }, expected: false },
        { name: 'not due on the legacy layout', state: { ...DUE, replayLayout: 'classic' }, expected: false },
        { name: 'not due for a layout override', state: { ...DUE, canOverrideLayout: true }, expected: false },
        { name: 'not due twice', state: { ...DUE, feedbackPromptShown: true }, expected: false },
        {
            name: 'not due after the switch-back survey',
            state: { ...DUE, switchBackSurveyShown: true },
            expected: false,
        },
    ] as { name: string; state: FeedbackPromptState; expected: boolean }[])(
        'prompt is $name',
        ({ state, expected }) => {
            expect(feedbackPromptDue(state)).toBe(expected)
        }
    )

    it.each([
        { arm: 'compact', days: ['2026-01-05', '2026-01-05', '2026-01-06'], expected: 2 },
        { arm: 'control', days: ['2026-01-05', '2026-01-06'], expected: 0 },
    ])('counts $expected distinct days for the $arm arm', ({ arm, days, expected }) => {
        setArm(arm)
        days.forEach(openOn)
        expect(logic.values.newLayoutVisitDays).toBe(expected)
    })

    it('reports a switch to legacy and asks why once', () => {
        setArm('youtube')
        openOn('2026-01-05')

        logic.actions.switchLayout(true, 'header_switch')
        logic.actions.switchLayout(false, 'layout_menu')
        logic.actions.switchLayout(true, 'layout_menu')

        expect(capture).toHaveBeenNthCalledWith(
            1,
            'session recording layout changed',
            expect.objectContaining({
                layout: 'classic',
                source: 'header_switch',
                replay_layout_arm: 'youtube',
                new_layout_visit_days: 1,
            })
        )
        expect(capture).toHaveBeenCalledTimes(3)
        expect(displaySurvey).toHaveBeenCalledTimes(1)
        expect(displaySurvey).toHaveBeenCalledWith('switch-back-survey', expect.anything())
    })

    it('shows the feedback prompt once, when a recording ends on the fifth day', () => {
        setArm('compact')
        ;['2026-01-05', '2026-01-06', '2026-01-07', '2026-01-08'].forEach(openOn)
        logic.actions.recordingEnded()
        expect(displaySurvey).not.toHaveBeenCalled()

        openOn('2026-01-09')
        logic.actions.recordingEnded()
        logic.actions.recordingEnded()

        expect(displaySurvey).toHaveBeenCalledTimes(1)
        expect(displaySurvey).toHaveBeenCalledWith(
            'feedback-survey',
            expect.objectContaining({ properties: expect.objectContaining({ trigger: 'visit_day_prompt' }) })
        )
    })
})
