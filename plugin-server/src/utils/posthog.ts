import { PostHog } from 'posthog-node'

import { Team } from '../types'

export const posthog = new PostHog('sTMFPsFhdP1Ssg', {
    host: 'https://us.i.posthog.com',
})

if (process.env.NODE_ENV === 'test') {
    posthog.disable()
}

export const captureTeamEvent = (team: Team, event: string, properties: Record<string, any> = {}): void => {
    posthog.capture({
        distinctId: team.uuid,
        event,
        properties: {
            team: team.uuid,
            ...properties,
        },
        groups: {
            project: team.uuid,
            organization: team.organization_id,
            instance: process.env.SITE_URL ?? 'unknown',
        },
    })
}
