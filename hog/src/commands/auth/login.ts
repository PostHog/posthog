import { printPending, resumeApproval, runApproval, type ApprovalResult } from '@/core/approval'
import { defineCommand } from '@/core/command'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import type { Prompts } from '@/core/prompts'
import { PersonalAPIKey } from '@/posthog/access-key'
import type { StoreChoice } from '@/posthog/credential-store/types'
import { checkApiKey, checkHost, checkProjectId } from '@/posthog/credentials'
import type { Approval } from '@/posthog/device-auth'
import { trimHost } from '@/posthog/host'
import { loginFlow, saveLogin, type LoggedIn } from '@/posthog/login/flow'

const REGIONS = { us: 'https://us.posthog.com', eu: 'https://eu.posthog.com' } as const

// A posthog.json comes with the repository, so it only picks between the PostHog Cloud regions.
// A login to any other host needs --host, because the key it gets is saved for every project.
function cloudRegion(host: string | undefined): string | undefined {
    if (host === undefined) {
        return undefined
    }
    let origin: string
    try {
        origin = new URL(host).origin
    } catch {
        return undefined
    }
    return Object.values(REGIONS).find((region) => region === origin)
}

type LoginResult =
    | (Extract<ApprovalResult<never>, { status: 'pending' }> & { host: string })
    | {
          status: 'logged_in'
          host: string
          projectId: string
          store: StoreChoice
          credentialsPath: string | null
          keychainError: string | null
          next: string
      }

function nextCommand(scopes: readonly string[]): string {
    const canQuery = scopes.some((scope) => scope === '*' || scope.startsWith('query:'))
    return canQuery ? 'hog query run "select event, count() from events group by event"' : 'hog --help'
}

function loggedInResult(loggedIn: LoggedIn): LoginResult {
    const { host, projectId, store, credentialsPath, keychainError, scopes } = loggedIn
    return { status: 'logged_in', host, projectId, store, credentialsPath, keychainError, next: nextCommand(scopes) }
}

async function finish(ctx: Context, approval: Approval): Promise<LoginResult> {
    const { host, apiKey, projectId, scopes } = approval
    const loggedIn = await saveLogin(ctx.runtime, new PersonalAPIKey({ host, projectId, apiKey, scopes }))
    return loggedInResult({ ...loggedIn, scopes })
}

async function keyLogin(ctx: Context, prompts: Prompts): Promise<LoginResult> {
    const host = await prompts.text('PostHog host', { initialValue: REGIONS.us, validate: checkHost })
    const projectId = await prompts.text('Project ID, the number in your project URL', { validate: checkProjectId })
    const apiKey = await prompts.password('Personal API key', { validate: checkApiKey })
    const key = new PersonalAPIKey({ host: trimHost(host), projectId, apiKey })
    return loggedInResult(await saveLogin(ctx.runtime, key))
}

export default defineCommand({
    description: 'Log in to PostHog',
    writes: true,
    options: {
        region: {
            type: 'string',
            choices: ['us', 'eu'],
            placeholder: 'region',
            description:
                'Where your PostHog account is hosted, as in the us.posthog.com or eu.posthog.com address. Use --host for self-hosted PostHog',
        },
        wait: {
            type: 'boolean',
            description: 'Wait for the login an agent or script started, and save the key once a person approves it',
        },
    },
    notes: [
        'At a terminal, hog asks where your PostHog account is hosted and opens the browser to approve the login.',
        'Agents and scripts get a link and a code to hand to a person, then finish with `hog auth login --wait`.',
        'hog stores the key in the system keychain. If no keychain is available, such as over SSH, it stores the key in a file only you can read.',
        'In CI, skip login and set HOG_PERSONAL_API_KEY, HOG_PROJECT_ID and HOG_HOST.',
    ].join('\n'),
    examples: ['hog auth login', 'hog auth login --region eu', 'hog auth login --wait'],

    async run({ options, ctx }): Promise<LoginResult> {
        const prompts = ctx.prompts

        if (options.wait) {
            return finish(ctx, await resumeApproval(ctx, loginFlow(ctx.runtime)))
        }

        if (!prompts && ctx.mode.agent === undefined && ctx.mode.ci) {
            throw new HogError(
                'login_needs_a_person',
                'hog auth login needs a person to approve it in a browser, so it does not run in CI.',
                'Set HOG_PERSONAL_API_KEY, HOG_PROJECT_ID and HOG_HOST instead.'
            )
        }

        let host =
            ctx.globals.host?.replace(/\/+$/, '') ??
            (options.region ? REGIONS[options.region] : undefined) ??
            cloudRegion((await ctx.config())?.config.host)
        if (!host) {
            if (!prompts) {
                throw new HogError(
                    'region_required',
                    'hog auth login needs to know where your PostHog account is hosted.',
                    'Ask the user where their PostHog account is hosted. When they open PostHog in a browser, the address starts with us.posthog.com or eu.posthog.com. Then run `hog auth login --region us` or `hog auth login --region eu`. For self-hosted PostHog, pass --host.',
                    EXIT_USAGE
                )
            }
            const choice = await prompts.select(
                'Where is your PostHog account hosted?',
                [
                    { value: 'us', label: 'US Cloud', hint: 'us.posthog.com' },
                    { value: 'eu', label: 'EU Cloud', hint: 'eu.posthog.com' },
                    {
                        value: 'key',
                        label: 'Paste a personal API key',
                        hint: 'for self-hosted PostHog, or without a browser',
                    },
                ],
                {
                    help: 'Open PostHog in your browser and check the address: it starts with us.posthog.com or eu.posthog.com.',
                }
            )
            if (choice === 'key') {
                return keyLogin(ctx, prompts)
            }
            host = REGIONS[choice]
        }

        const result = await runApproval(ctx, loginFlow(ctx.runtime, host))
        return result.status === 'pending' ? { ...result, host } : finish(ctx, result.value)
    },

    human({ result, out }) {
        if (result.status === 'pending') {
            printPending(out, result)
            return
        }
        out.line(`${out.style('Logged in', 'green', 'bold')} to ${result.host}, project ${result.projectId}.`)
        switch (result.store) {
            case 'keychain':
                out.line(out.style('Credentials saved to the system keychain', 'dim'))
                break
            case 'file':
                if (result.keychainError) {
                    out.line(out.style(`${escapeControls(result.keychainError).replace(/\.$/, '')}.`, 'yellow'))
                }
                out.line(out.style(`Credentials saved to ${result.credentialsPath}, which only you can read`, 'dim'))
                break
        }
        out.line(`Try it: ${result.next}`)
    },
})
