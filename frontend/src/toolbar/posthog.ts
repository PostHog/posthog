import { browserPostHog } from 'posthog-js-lite/dist/src/targets/browser'

const apiKey = 'sTMFPsFhdP1Ssg'
const apiHost = 'https://app.posthog.com'

export const posthog = browserPostHog(apiKey, {
    apiHost: apiHost,
    optedIn: false, // must call .optIn() before any events are sent
})
