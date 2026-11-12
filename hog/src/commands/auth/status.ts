import { defineCommand } from '@/core/command'
import { escapeControls } from '@/core/output'
import { checkAuthStatus } from '@/posthog/auth-status'
import type { StoreChoice } from '@/posthog/credential-store/types'
import type { CredentialSource } from '@/posthog/credentials'

function sourceLabel(
    source: CredentialSource,
    store: StoreChoice | null,
    path: string | null,
    provider: string | null
): string {
    switch (source) {
        case 'env':
            return 'the HOG_PERSONAL_API_KEY environment variable'
        case 'dotenv-file':
            return `HOG_PERSONAL_API_KEY in ${path}`
        case 'store':
            return store === 'keychain' ? 'the system keychain' : `${path}`
        case 'workload':
            return `this job's ${provider} OIDC token`
    }
}

export default defineCommand({
    description: 'Show whether hog is logged in, where its credentials come from, and what they can do',
    notes: [
        'Each project has its own login. Status shows the posthog.json it found, the login it uses, and why.',
        'Without a project in posthog.json or HOG_PROJECT_ID, commands use your latest login to the host.',
        'Exits with code 1 when hog has no working credentials, so scripts and agents can branch on it.',
    ].join('\n'),
    examples: ['hog auth status', 'hog auth status -o json'],

    run: ({ ctx }) => checkAuthStatus(ctx),

    human({ result, out }) {
        if (!result.authenticated) {
            out.report({
                status: 'failed',
                result: result.error ? `Not logged in: ${result.error}` : 'Not logged in',
                notes: [`Run ${out.style(result.next, 'bold')} next.`],
            })
            return
        }
        // The email and project name come from PostHog, and anyone who can rename the project sets the name.
        const who = result.user ? ` as ${out.style(escapeControls(result.user.email), 'bold')}` : ''
        out.line(`${out.style('Logged in', 'green', 'bold')} to ${escapeControls(result.host)}${who}.`)
        const name = result.projectName ? escapeControls(result.projectName) : null
        out.line(`Project: ${name ? `${name} (${result.projectId})` : result.projectId}`)
        const what = { oauth: 'Token', personal_api_key: 'Personal API key', workload: 'Workload token' }[result.kind]
        const source = sourceLabel(result.source, result.store, result.credentialsPath, result.provider)
        out.line(out.style(`${what} from ${source}`, 'dim'))
        if (result.scopes) {
            out.line(out.style(`Scopes: ${result.scopes.join(', ')}`, 'dim'))
        }
        if (result.expiresAt) {
            out.line(out.style(`Expires ${result.expiresAt}. hog renews it before then.`, 'dim'))
        }
        out.line(
            out.style(
                result.config ? `Config: ${escapeControls(result.config)}` : 'Config: no posthog.json found',
                'dim'
            )
        )
        if (result.login) {
            out.line(out.style(`Login picked because ${escapeControls(result.login.reason)}.`, 'dim'))
        }
    },

    exitCode: (result) => (result.authenticated ? 0 : 1),
})
