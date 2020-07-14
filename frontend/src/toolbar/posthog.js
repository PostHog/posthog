import { browserPostHog } from 'posthog-js-lite/dist/src/targets/browser'

const apiKey = 'sTMFPsFhdP1Ssg'
const apiHost = 'https://app.posthog.com'

// const apiKey = '8jVz0YZ2YPtP7eL1I5l5RQIp-WcuFeD3pZO8c0YDMx4'
// const apiHost = 'http://localhost:8000'

function setupPostHog() {
    const posthog = browserPostHog(apiKey, {
        apiHost: apiHost,
        optedIn: false, // must call .optIn() before any events are sent
    })
    return posthog
}
export const posthog = setupPostHog()
