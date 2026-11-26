import { defineCommand } from '@/core/command'
import { EXIT_FAILURE, EXIT_SUCCESS } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { checkAuthStatus } from '@/posthog/auth-status'
import type { StoreChoice } from '@/posthog/credential-store/types'
import type { CredentialSource } from '@/posthog/credentials'
import { currentVersionInfo, updateChecksOff } from '@/updates/check'

// Where the credentials come from, as a person reads it: what kind of login, and where hog keeps it.
function loginLabel(
    kind: 'oauth' | 'personal_api_key' | 'workload',
    source: CredentialSource,
    store: StoreChoice | null,
    path: string | null,
    provider: string | null
): string {
    switch (source) {
        case 'env':
            return 'Personal API key from HOG_PERSONAL_API_KEY'
        case 'dotenv-file':
            return `Personal API key from HOG_PERSONAL_API_KEY in ${path}`
        case 'workload':
            return `This job's ${provider} OIDC token`
        case 'store': {
            const where = store === 'keychain' ? 'the system keychain' : `${path}`
            return kind === 'oauth'
                ? `Browser login in ${where}, renewed automatically`
                : `Personal API key in ${where}`
        }
    }
}

// A login holds dozens of scopes, so a person sees how many it can write and read. Only a short
// list is spelled out.
const IDENTITY_SCOPES = new Set(['openid', 'profile', 'email'])
const LISTED_SCOPES = 4

function accessLabel(scopes: readonly string[]): string {
    const data = scopes.filter((scope) => !IDENTITY_SCOPES.has(scope))
    if (data.includes('*')) {
        return 'Every scope'
    }
    if (data.length <= LISTED_SCOPES) {
        // The scopes come from the host's token response, so escape sequences in them must not reach the terminal.
        return data.length ? data.map(escapeControls).join(', ') : 'No data scopes'
    }
    const writes = data.filter((scope) => scope.endsWith(':write')).length
    const reads = data.length - writes
    const counts = [writes ? `${writes} write` : '', reads ? `${reads} read` : ''].filter(Boolean).join(' and ')
    return `${counts} scopes. hog api access lists them`
}

export default defineCommand({
    description: 'Show whether hog is logged in, where its credentials come from, and what they can do',
    notes: [
        'Each project has its own login. Status shows the posthog.json it found, the login it uses, and why.',
        'Without a project in posthog.json or HOG_PROJECT_ID, commands use your latest login to the host.',
        'Exits with code 1 when hog has no working credentials, so scripts and agents can branch on it.',
    ].join('\n'),
    examples: ['hog auth status', 'hog auth status -o json'],

    // Agents read `hog` to see whether to run `hog upgrade` first.
    run: async ({ ctx }) => {
        const config = await ctx.config().catch(() => undefined)
        const off = updateChecksOff(ctx.runtime, config?.config) || ctx.globals.skipSslVerification === true
        const [status, hog] = await Promise.all([checkAuthStatus(ctx), currentVersionInfo(ctx.runtime, off)])
        return { ...status, hog }
    },

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
        const name = result.projectName ? escapeControls(result.projectName) : null
        const rows: [string, string | null][] = [
            ['Host', escapeControls(result.host)],
            ['Project', name ? `${name} (${result.projectId})` : result.projectId],
            ['Login', loginLabel(result.kind, result.source, result.store, result.credentialsPath, result.provider)],
            ['Access', result.scopes ? accessLabel(result.scopes) : null],
            ['Config', result.config ? escapeControls(result.config) : 'No posthog.json'],
        ]

        out.line(`${out.style('✓', 'green', 'bold')} Logged in${who}`)
        out.line()
        for (const [label, value] of rows) {
            if (value !== null) {
                out.line(`  ${out.style(label.padEnd(10), 'bold')}${value}`)
            }
        }
        // posthog.json naming the project explains itself. Any other pick says why.
        if (result.login && result.login.match !== 'exact') {
            out.notes({
                notes: [out.style(`hog picked this login because ${escapeControls(result.login.reason)}.`, 'dim')],
            })
        }
    },

    exitCode: (result) => (result.authenticated ? EXIT_SUCCESS : EXIT_FAILURE),
})
