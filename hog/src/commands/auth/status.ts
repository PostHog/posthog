import { defineCommand } from '@/core/command'
import { HogError } from '@/core/errors'
import { ApiError } from '@/posthog/api'
import { posthogFile, type CredentialSource } from '@/posthog/credentials'

type StatusResult =
    | {
          authenticated: false
          next: string
          problem?: string
          host?: string
          projectId?: string
          source?: CredentialSource
      }
    | {
          authenticated: true
          host: string
          projectId: string
          projectName: string | null
          source: CredentialSource
          credentialsPath: string | null
          // Null when the key lacks the user:read scope, so hog can't tell whose key it is.
          user: { email: string; name: string | null } | null
      }

const SOURCE_LABELS: Record<CredentialSource, string> = {
    env: 'the POSTHOG_CLI_API_KEY environment variable',
    'dotenv-file': 'the --dotenv-file file',
    'credentials-file': 'the credentials file',
}

export default defineCommand({
    description: 'Show whether hog is logged in, where its key comes from, and whose key it is',
    notes: 'Exits with code 1 when hog has no working key, so scripts and agents can branch on it.',
    examples: ['hog auth status', 'hog auth status -o json'],

    async run({ ctx }): Promise<StatusResult> {
        let credentials
        try {
            credentials = await ctx.credentials()
        } catch (error) {
            if (error instanceof HogError && error.code === 'not_authenticated') {
                return { authenticated: false, next: 'hog auth login' }
            }
            throw error
        }
        const { host, projectId, source } = credentials
        const api = await ctx.posthog()
        const [user, project] = await Promise.allSettled([
            api.get<{ email: string; first_name?: string }>('/api/users/@me/'),
            api.get<{ name: string }>(''),
        ])
        const rejected = [user, project].find((outcome) => outcome.status === 'rejected')?.reason
        if (rejected instanceof ApiError && rejected.status === 401) {
            return {
                authenticated: false,
                host,
                projectId,
                source,
                problem: 'PostHog rejected the key. Someone may have deleted it.',
                next: 'hog auth login',
            }
        }
        // A 403 means the key lacks the scope for that detail, not that it doesn't work.
        if (rejected !== undefined && !(rejected instanceof ApiError && rejected.status === 403)) {
            throw rejected
        }
        return {
            authenticated: true,
            host,
            projectId,
            projectName: project.status === 'fulfilled' ? project.value.name : null,
            source,
            credentialsPath: source === 'credentials-file' ? posthogFile(ctx.runtime, 'credentials.json') : null,
            user: user.status === 'fulfilled' ? { email: user.value.email, name: user.value.first_name || null } : null,
        }
    },

    human({ result, out }) {
        if (!result.authenticated) {
            out.line(
                out.style(result.problem ? `Not logged in: ${result.problem}` : 'Not logged in.', 'yellow', 'bold')
            )
            out.line(`Run ${out.style(result.next, 'bold')} to log in.`)
            return
        }
        const who = result.user ? ` as ${out.style(result.user.email, 'bold')}` : ''
        out.line(`${out.style('Logged in', 'green', 'bold')} to ${result.host}${who}.`)
        out.line(`Project: ${result.projectName ? `${result.projectName} (${result.projectId})` : result.projectId}`)
        out.line(out.style(`Key from ${result.credentialsPath ?? SOURCE_LABELS[result.source]}`, 'dim'))
    },

    exitCode: (result) => (result.authenticated ? 0 : 1),
})
