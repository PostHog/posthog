import {
    makeFeedback,
    makeFeedbackScore,
    makeFeedbackText,
    makeSurveyResponse,
    makeTraceResource,
} from './testFixtures'
import { stepFeedbackOf, toFeedbackChip, toFeedbackMode, toStepFeedback } from './toFeedback'

describe('toFeedback', () => {
    test.each([
        ['thumbs', { total: 4, thumbsUp: 1, thumbsDown: 1 }, { total: 4, thumbsUp: 1, thumbsDown: 1 }],
        ['nothing', { total: 0, thumbsUp: 0, thumbsDown: 0 }, null],
    ])('toFeedbackChip with %s', (_name, summary, expected) => {
        expect(toFeedbackChip(summary)).toEqual(expected)
    })

    test.each(['trace-1', 'constructor', '__proto__'])(
        'toStepFeedback puts each entry on its step and trace-level entries and survey responses on the root %s',
        (traceId) => {
            const score = makeFeedbackScore({ nodeId: 'gen-1' })
            const traceScore = makeFeedbackScore({ id: 'score-2', nodeId: traceId })
            const feedback = makeFeedback({
                scores: [score, traceScore],
                responses: [
                    makeFeedbackText({ nodeId: 'gen-1' }),
                    makeFeedbackText({ id: 'text-2', nodeId: traceId }),
                    makeSurveyResponse({ nodeId: traceId }),
                ],
            })

            expect({ ...toStepFeedback(feedback) }).toEqual({
                'gen-1': { scores: [score], responseCount: 1 },
                [traceId]: { scores: [traceScore], responseCount: 2 },
            })
        }
    )

    test.each(['trace-1', 'constructor', '__proto__'])(
        'stepFeedbackOf finds the root %s only when it has feedback',
        (traceId) => {
            const traceScore = makeFeedbackScore({ nodeId: traceId })
            const withFeedback = toStepFeedback(makeFeedback({ scores: [traceScore], responses: [] }))

            expect(stepFeedbackOf({}, traceId)).toBeNull()
            expect(stepFeedbackOf(withFeedback, traceId)).toEqual({ scores: [traceScore], responseCount: 0 })
        }
    )

    test('toFeedbackMode names each step, keeps the root and an unknown step as trace-level and survey responses as they come', () => {
        const survey = makeSurveyResponse()
        const unanswered = [{ survey: { id: 'survey-2', name: 'Follow-up' }, timestamp: '2026-09-01T10:19:00Z' }]
        const feedback = makeFeedback({
            scores: [makeFeedbackScore({ nodeId: 'gen-1' }), makeFeedbackScore({ id: 'score-2', nodeId: 'gone' })],
            responses: [makeFeedbackText({ nodeId: 'trace-1' }), survey],
            unanswered,
            surveyResponsesStatus: 'failed',
        })

        const mode = toFeedbackMode({ feedback, tree: makeTraceResource().tree, traceId: 'trace-1', focusNodeId: null })

        expect(mode.scores.map((row) => row.step)).toEqual([{ id: 'gen-1', name: 'gen-1' }, null])
        expect(mode.responses.map((item) => item.step)).toEqual([null, null])
        expect(mode.responses[1]).toEqual({ ...survey, step: null, focused: false })
        expect(mode.unanswered).toEqual(unanswered)
        expect(mode.surveysFailed).toBe(true)
    })

    test.each([
        ['a step', 'gen-1', [true, false], [false]],
        ['the root, which holds the trace-level entries', 'trace-1', [false, true], [true]],
        ['nothing', null, [false, false], [false]],
    ])('toFeedbackMode focuses the entries of %s', (_name, focusNodeId, scoresFocused, responsesFocused) => {
        const feedback = makeFeedback({
            scores: [makeFeedbackScore({ nodeId: 'gen-1' }), makeFeedbackScore({ id: 'score-2', nodeId: 'trace-1' })],
            responses: [makeFeedbackText({ nodeId: 'trace-1' })],
        })

        const mode = toFeedbackMode({ feedback, tree: makeTraceResource().tree, traceId: 'trace-1', focusNodeId })

        expect(mode.scores.map((row) => row.focused)).toEqual(scoresFocused)
        expect(mode.responses.map((item) => item.focused)).toEqual(responsesFocused)
    })
})
