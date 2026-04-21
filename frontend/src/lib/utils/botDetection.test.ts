import { detectBot, getBotName, isBot } from './botDetection'

describe('botDetection', () => {
    describe('detectBot', () => {
        it.each([
            [
                'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)',
                'GPTBot',
                'ai_crawler',
            ],
            ['ChatGPT-User/1.0; +https://openai.com/bot', 'ChatGPT', 'ai_assistant'],
            ['Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)', 'Claude', 'ai_crawler'],
            [
                'Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)',
                'Perplexity',
                'ai_search',
            ],
            ['Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)', 'Googlebot', 'search_crawler'],
            ['curl/8.5.0', 'curl', 'http_client'],
            ['Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)', 'Bingbot', 'search_crawler'],
            ['HeadlessChrome/120.0.6099.216', 'Headless Chrome', 'headless_browser'],
        ])('detects bot from user agent: %s', (userAgent, expectedName, expectedCategory) => {
            const bot = detectBot(userAgent)
            expect(bot).not.toBeNull()
            expect(bot?.name).toBe(expectedName)
            expect(bot?.category).toBe(expectedCategory)
        })

        it('prefers Applebot-Extended over Applebot/ when the more specific pattern matches first', () => {
            const bot = detectBot('Mozilla/5.0 (compatible; Applebot-Extended/1.0)')
            expect(bot?.name).toBe('Apple AI')
        })

        it('classifies regular Applebot to the search crawler entry', () => {
            const bot = detectBot('Mozilla/5.0 Applebot/0.1')
            expect(bot?.name).toBe('Applebot')
        })

        it('returns null for regular browser user agents', () => {
            expect(
                detectBot(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
            ).toBeNull()
        })

        it('returns null for empty or missing user agent', () => {
            expect(detectBot('')).toBeNull()
            expect(detectBot(null)).toBeNull()
            expect(detectBot(undefined)).toBeNull()
        })
    })

    describe('getBotName', () => {
        it('returns the bot name for a known bot', () => {
            expect(getBotName('Googlebot/2.1')).toBe('Googlebot')
        })
        it('returns "" for regular traffic', () => {
            expect(getBotName('Mozilla/5.0 Chrome/120.0.0.0')).toBe('')
        })
    })

    describe('isBot', () => {
        it('returns true for a known bot', () => {
            expect(isBot('GPTBot/1.0')).toBe(true)
        })
        it('returns false for empty or missing user agent', () => {
            expect(isBot('')).toBe(false)
            expect(isBot(null)).toBe(false)
        })
        it('returns false for a regular browser', () => {
            expect(isBot('Mozilla/5.0 Chrome/120.0.0.0 Safari/537.36')).toBe(false)
        })
    })
})
