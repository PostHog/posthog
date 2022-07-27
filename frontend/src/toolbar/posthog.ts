import PostHog from 'posthog-js-lite'

const apiKey = 'sTMFPsFhdP1Ssg'
const apiHost = 'https://app.posthog.com'

export const posthog = new PostHog(apiKey, {
    host: apiHost,
    enable: false, // must call .optIn() before any events are sent
    persistence_name: apiKey + '_toolbar',
})
