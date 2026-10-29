import { defineCommand } from '@/core/command'
import { escapeControls } from '@/core/output'
import { checkAuthStatus } from '@/posthog/auth-status'
import type { CredentialSource } from '@/posthog/credentials'

const SOURCE_LABELS: Record<CredentialSource, string> = {
    env: 'the HOG_API_KEY environment variable',
    'dotenv-file': 'the --dotenv-file file',
    'credentials-file': 'the credentials file',
}

export default defineCommand({
    description: 'Show whether hog is logged in, where its key comes from, and whose key it is',
    notes: 'Exits with code 1 when hog has no working key, so scripts and agents can branch on it.',
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
        out.line(out.style(`Key from ${result.credentialsPath ?? SOURCE_LABELS[result.source]}`, 'dim'))
    },

    exitCode: (result) => (result.authenticated ? 0 : 1),
})
