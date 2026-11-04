import { defineCommand } from '@/core/command'
import { escapeControls } from '@/core/output'
import { checkAuthStatus } from '@/posthog/auth-status'
import type { StoreChoice } from '@/posthog/credential-store/types'
import type { CredentialSource } from '@/posthog/credentials'

function sourceLabel(source: CredentialSource, store: StoreChoice | null, path: string | null): string {
    switch (source) {
        case 'env':
            return 'the HOG_PERSONAL_API_KEY environment variable'
        case 'dotenv-file':
            return `HOG_PERSONAL_API_KEY in ${path}`
        case 'store':
            return store === 'keychain' ? 'the system keychain' : `${path}`
    }
}

export default defineCommand({
    description: 'Show whether hog is logged in, where its credentials come from, and what they can do',
    notes: 'Exits with code 1 when hog has no working credentials, so scripts and agents can branch on it.',
    examples: ['hog auth status', 'hog auth status -o json'],

    run: ({ ctx }) => checkAuthStatus(ctx),

    human({ result, out }) {
        if (!result.authenticated) {
            out.line(out.style(result.error ? `Not logged in: ${result.error}` : 'Not logged in.', 'yellow', 'bold'))
            out.line(`Run ${out.style(result.next, 'bold')} to log in.`)
            return
        }
        // The email and project name come from PostHog, and anyone who can rename the project sets the name.
        const who = result.user ? ` as ${out.style(escapeControls(result.user.email), 'bold')}` : ''
        out.line(`${out.style('Logged in', 'green', 'bold')} to ${escapeControls(result.host)}${who}.`)
        const name = result.projectName ? escapeControls(result.projectName) : null
        out.line(`Project: ${name ? `${name} (${result.projectId})` : result.projectId}`)
        const what = result.kind === 'oauth' ? 'Token' : 'Personal API key'
        out.line(out.style(`${what} from ${sourceLabel(result.source, result.store, result.credentialsPath)}`, 'dim'))
        if (result.scopes) {
            out.line(out.style(`Scopes: ${result.scopes.join(', ')}`, 'dim'))
        }
        if (result.expiresAt) {
            out.line(out.style(`Expires ${result.expiresAt}. hog renews it before then.`, 'dim'))
        }
    },

    exitCode: (result) => (result.authenticated ? 0 : 1),
})
