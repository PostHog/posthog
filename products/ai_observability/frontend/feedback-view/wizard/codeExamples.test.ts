import { getManualCaptureExample } from './codeExamples'

interface SamplePath {
    followUpEnabled?: boolean
    clickedThumbsUp: boolean
    followUpText?: string
}

// Run the generated sample against a stub, so the assertions read the events a pasted
// integration sends rather than the text of the snippet.
function runSample({
    followUpEnabled = true,
    clickedThumbsUp,
    followUpText = '',
}: SamplePath): Record<string, unknown>[] {
    const sent: Record<string, unknown>[] = []
    const posthog = {
        capture: (event: string, properties: Record<string, unknown>): void => {
            if (event === 'survey sent') {
                sent.push(properties)
            }
        },
    }

    const sample = new Function(
        'posthog',
        'crypto',
        'traceId',
        'clickedThumbsUp',
        'followUpText',
        getManualCaptureExample({ surveyId: 'survey-1', followUpEnabled })
    )
    sample(posthog, { randomUUID: () => 'submission-1' }, 'trace-1', clickedThumbsUp, followUpText)

    return sent
}

describe('getManualCaptureExample', () => {
    describe('with a follow-up question', () => {
        // Results keeps one row per `$survey_submission_id` and drops a submission that has no
        // completed event. So every path has to end on exactly one completed event, and that
        // event has to carry every answer given so far.
        it.each([
            {
                path: 'a thumbs up, which branches straight to the end',
                clickedThumbsUp: true,
                followUpText: '',
                eventsSent: 1,
                rating: 1,
                answer: undefined,
            },
            {
                path: 'a thumbs down with follow-up text',
                clickedThumbsUp: false,
                followUpText: 'the AI hallucinated hedgehogs everywhere',
                eventsSent: 2,
                rating: 2,
                answer: 'the AI hallucinated hedgehogs everywhere',
            },
            {
                path: 'a thumbs down whose follow-up is dismissed',
                clickedThumbsUp: false,
                followUpText: '',
                eventsSent: 2,
                rating: 2,
                answer: '',
            },
        ])('completes $path with every answer on the completed event', (testCase) => {
            // The sample wires its second capture to the follow-up closing, so a straight run
            // reaches it on every path. `eventsSent` trims the run back to one real path.
            const sent = runSample(testCase).slice(0, testCase.eventsSent)

            const completed = sent.filter((event) => event.$survey_completed === true)
            expect(completed).toHaveLength(1)
            expect(completed[0].$survey_response).toBe(testCase.rating)
            expect(completed[0].$survey_response_1).toBe(testCase.answer)
            expect(new Set(sent.map((event) => event.$survey_submission_id)).size).toBe(1)
        })
    })

    it('reads the rating off the click when there is no follow-up', () => {
        const [sent] = runSample({ followUpEnabled: false, clickedThumbsUp: false })

        expect(sent.$survey_response).toBe(2)
    })
})
