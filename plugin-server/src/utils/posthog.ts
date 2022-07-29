import PostHog from 'posthog-node'

export const posthog = new PostHog('sTMFPsFhdP1Ssg', {
    host: 'https://app.posthog.com',
})

if (process.env.NODE_ENV === 'test') {
    posthog.disable()
}
