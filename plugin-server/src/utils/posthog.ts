import { PostHog } from 'posthog-node'

export const posthog = new PostHog('sTMFPsFhdP1Ssg', {
    host: 'https://us.i.posthog.com',
})

if (process.env.NODE_ENV === 'test') {
    posthog.disable()
}
