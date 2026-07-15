import { ThreadMessage } from './maxLogic'
import { getTicketSummaryData } from './ticketUtils'

const human = (content: string): ThreadMessage => ({ type: 'human', content }) as unknown as ThreadMessage
const ai = (content: string): ThreadMessage => ({ type: 'ai', content }) as unknown as ThreadMessage

const SUMMARY = 'PostHog AI Support Ticket Summary:\n\nIssue: Session recordings are not appearing in the dashboard.'
const DENIAL =
    'The `/ticket` command is available for customers on paid plans or active trials. You can upgrade your plan in the billing settings, or ask the community at https://posthog.com/questions for help. If your issue is about billing, you can always contact our support team through the in-app help panel.'

describe('getTicketSummaryData', () => {
    it('does not treat an eligibility denial as a ticket summary', () => {
        const thread = [
            human('How do I create an insight?'),
            ai('You can create an insight by...'),
            human('/ticket'),
            ai(DENIAL),
        ]

        expect(getTicketSummaryData(thread, false)).toBeNull()
    })

    it('returns the summary when the response after /ticket is a real summary', () => {
        const thread = [
            human('How do I create an insight?'),
            ai('You can create an insight by...'),
            human('/ticket'),
            ai(SUMMARY),
        ]

        expect(getTicketSummaryData(thread, false)).toEqual({ summary: SUMMARY, messageIndex: 3 })
    })
})
