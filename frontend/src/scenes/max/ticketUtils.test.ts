import { ThreadMessage } from './maxLogic'
import { getTicketSummaryData, parseTicketTargetArea } from './ticketUtils'

const human = (content: string): ThreadMessage => ({ type: 'human', content }) as unknown as ThreadMessage
const ai = (content: string): ThreadMessage => ({ type: 'ai', content }) as unknown as ThreadMessage

const SUMMARY = 'PostHog AI Support Ticket Summary:\n\nIssue: Session recordings are not appearing in the dashboard.'
const SUMMARY_WITH_TOPIC = `${SUMMARY}\n\n**Topic:** session_replay`
const DENIAL =
    'The `/ticket` command is available for customers on paid plans or active trials. You can upgrade your plan in the billing settings, or ask the community at https://posthog.com/questions for help. If your issue is about billing, you can always contact our support team through the in-app help panel.'

describe('ticketUtils', () => {
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

            expect(getTicketSummaryData(thread, false)).toEqual({ summary: SUMMARY, messageIndex: 3, targetArea: null })
        })

        it('extracts the target area from the summary topic line', () => {
            const thread = [
                human('My recordings are missing'),
                ai('Let me check that...'),
                human('/ticket'),
                ai(SUMMARY_WITH_TOPIC),
            ]

            expect(getTicketSummaryData(thread, false)).toEqual({
                summary: SUMMARY_WITH_TOPIC,
                messageIndex: 3,
                targetArea: 'session_replay',
            })
        })
    })

    describe('parseTicketTargetArea', () => {
        it.each([
            ['bold topic line with valid area', 'Issue: foo\n\n**Topic:** data_warehouse', 'data_warehouse'],
            ['plain topic line with valid area', 'Issue: foo\n\nTopic: session_replay', 'session_replay'],
            ['case and whitespace variations', 'Issue: foo\n\ntopic:   Data_Warehouse  ', 'data_warehouse'],
            ['unknown area is rejected', 'Issue: foo\n\nTopic: quantum_computing', null],
            ['no topic line', 'Issue: foo\n\nStatus: bar', null],
            ['topic mentioned mid-sentence is ignored', 'Issue: the topic: billing came up in chat', null],
        ])('%s', (_name, content, expected) => {
            expect(parseTicketTargetArea(content)).toBe(expected)
        })
    })
})
