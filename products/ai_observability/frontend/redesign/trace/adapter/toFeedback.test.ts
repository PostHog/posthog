import { makeFeedback, makeFeedbackScore, makeFeedbackText, makeTraceResource } from './testFixtures'
import { toFeedbackChip, toFeedbackMode, toStepFeedback } from './toFeedback'

describe('toFeedback', () => {
    test.each([
        ['some', 3, { total: 3 }],
        ['none', 0, null],
    ])('toFeedbackChip with %s feedback', (_name, total, expected) => {
        expect(toFeedbackChip({ total })).toEqual(expected)
    })

    test('toStepFeedback puts trace-level entries and entries on a step the tree lacks on the root', () => {
        const score = makeFeedbackScore({ nodeId: 'gen-1' })
        const traceScore = makeFeedbackScore({ id: 'score-2', nodeId: null })
        const orphanScore = makeFeedbackScore({ id: 'score-3', nodeId: 'gone' })
        const feedback = makeFeedback({
            scores: [score, traceScore, orphanScore],
            responses: [makeFeedbackText({ nodeId: 'gen-1' }), makeFeedbackText({ id: 'text-2', nodeId: null })],
        })

        expect(toStepFeedback(feedback, makeTraceResource().tree, 'trace-1')).toEqual({
            'gen-1': { scores: [score], textCount: 1 },
            'trace-1': { scores: [traceScore, orphanScore], textCount: 1 },
        })
    })

    test('toFeedbackMode names each step and keeps an unknown step as trace-level', () => {
        const feedback = makeFeedback({
            scores: [makeFeedbackScore({ nodeId: 'gen-1' }), makeFeedbackScore({ id: 'score-2', nodeId: 'gone' })],
            responses: [makeFeedbackText({ nodeId: null })],
        })

        const mode = toFeedbackMode({ feedback, tree: makeTraceResource().tree, traceId: 'trace-1', focusNodeId: null })

        expect(mode.scores.map((row) => row.step)).toEqual([{ id: 'gen-1', name: 'gen-1' }, null])
        expect(mode.responses.map((item) => item.step)).toEqual([null])
    })

    test.each([
        ['a step', 'gen-1', [true, false], [false]],
        ['the root, which holds the trace-level entries', 'trace-1', [false, true], [true]],
        ['nothing', null, [false, false], [false]],
    ])('toFeedbackMode focuses the entries of %s', (_name, focusNodeId, scoresFocused, responsesFocused) => {
        const feedback = makeFeedback({
            scores: [makeFeedbackScore({ nodeId: 'gen-1' }), makeFeedbackScore({ id: 'score-2', nodeId: null })],
            responses: [makeFeedbackText({ nodeId: null })],
        })

        const mode = toFeedbackMode({ feedback, tree: makeTraceResource().tree, traceId: 'trace-1', focusNodeId })

        expect(mode.scores.map((row) => row.focused)).toEqual(scoresFocused)
        expect(mode.responses.map((item) => item.focused)).toEqual(responsesFocused)
    })
})
