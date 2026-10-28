import { getReferralFollowUp } from 'lib/components/SignupReferralSource'

describe('signup referral source follow-up triggers', () => {
    test.each([
        ['ChatGPT recommended it', 'ai'],
        ['claude', 'ai'],
        ['a web search', null],
        ['a colleague', null],
        ['found it on TikTok', 'influencer'],
        ['instagram', 'influencer'],
        ['a YouTuber I follow', 'influencer'],
        ['saw a tweet', 'influencer'],
        ['an influencer', 'influencer'],
        // When both patterns match, the AI prompt wins
        ['an AI influencer on YouTube', 'ai'],
        // "max" must not match the bare "x" pattern inside a word
        ['my friend max', null],
    ] as const)('"%s" → %s', (input, followUp) => {
        expect(getReferralFollowUp(input)).toBe(followUp)
    })
})
