export const BOT_NAME = 'PostHogImageFetcherBot'

export const REQUEST_IDENTITY_HEADERS: Readonly<Record<string, string>> = {
    'user-agent': `${BOT_NAME}/1.0 (+https://posthog.com/docs/ai-research/image-fetcher-bot)`,
    // Replay customers already allow requests from this host so that the replay viewer works. Change it before this lane runs outside prod-us.
    referer: 'https://us.posthog.com/',
}
