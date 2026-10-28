import { AI_REFERRAL_PATTERN, SOCIAL_REFERRAL_PATTERN } from 'lib/components/SignupReferralSource'

describe('signup referral source follow-up triggers', () => {
    test.each([
        ['ChatGPT recommended it', true, false],
        ['claude', true, false],
        ['a web search', false, false],
        ['a colleague', false, false],
        ['found it on TikTok', false, true],
        ['instagram', false, true],
        ['a YouTuber I follow', false, true],
        ['saw a tweet', false, true],
        ['an influencer', false, true],
        ['an AI influencer on YouTube', true, true],
        // "max" must not match the bare "x" pattern inside a word
        ['my friend max', false, false],
    ])('"%s" → ai: %s, influencer: %s', (input, ai, influencer) => {
        expect(AI_REFERRAL_PATTERN.test(input)).toBe(ai)
        expect(SOCIAL_REFERRAL_PATTERN.test(input)).toBe(influencer)
    })
})
