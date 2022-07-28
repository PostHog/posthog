import PostHog from 'posthog-js-lite'

const runningOnPosthog = !!window.POSTHOG_APP_CONTEXT
const apiKey = runningOnPosthog ? window.JS_POSTHOG_API_KEY : 'sTMFPsFhdP1Ssg'
const apiHost = runningOnPosthog ? window.JS_POSTHOG_HOST : 'https://app.posthog.com'

export const posthog = new PostHog(apiKey, {
    host: apiHost,
    enable: false, // must call .optIn() before any events are sent
    persistence_name: apiKey + '_toolbar',
})

if (runningOnPosthog && window.JS_POSTHOG_SELF_CAPTURE) {
    posthog.debug()
}
