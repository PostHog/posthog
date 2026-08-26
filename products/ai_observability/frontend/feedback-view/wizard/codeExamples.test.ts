import { getManualCaptureExample } from './codeExamples'

describe('getManualCaptureExample', () => {
    it('does not mark the rating event incomplete for a rating that ends the survey', () => {
        const thumbsEvent = getManualCaptureExample({ followUpEnabled: true })
            .split("posthog.capture('survey sent', {")[1]
            .split('})')[0]

        // The wizard branches a thumbs up straight to End, so it never sends a follow-up event.
        // A literal `false` here leaves every thumbs up submission without a completed event,
        // which hides it from surveys that do not enable partial responses.
        expect(thumbsEvent).not.toMatch(/\$survey_completed: false\b/)
    })
})
