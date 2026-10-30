import { defineCommand } from '@/core/command'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import type { Prompts, Spinner } from '@/core/prompts'
import { checkApiKey, checkHost, checkProjectId } from '@/posthog/credentials'
import type { PendingLogin } from '@/posthog/device-auth'
import { completeLogin, readPendingLogin, saveLogin, startLogin, type LoggedIn } from '@/posthog/login'

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
    | {
          status: 'pending'
          host: string
          url: string
          code: string
          expiresAt: string
          instructions: string
          next: string
      }
    | { status: 'logged_in'; host: string; projectId: string; credentialsPath: string; next: string }

function isTruthy(value: string | undefined): boolean {
    return value !== undefined && value !== '' && value !== '0' && value.toLowerCase() !== 'false'
}

function nextCommand(scopes: readonly string[]): string {
    const canQuery = scopes.some((scope) => scope === '*' || scope.startsWith('query:'))
    return canQuery ? 'hog query run "select event, count() from events group by event"' : 'hog --help'
}

function pendingResult(pending: PendingLogin): LoginResult {
    return {
        status: 'pending',
        host: pending.host,
        url: pending.url,
        code: pending.userCode,
        expiresAt: new Date(pending.expiresAt).toISOString(),
        instructions: `Ask the user to open ${pending.url} and approve the code ${pending.userCode}. Then run \`hog auth login --wait\`, which returns once they approve. If it times out, run it again.`,
        next: 'hog auth login --wait',
    }
}

function loggedInResult(loggedIn: LoggedIn): LoginResult {
    const { host, projectId, credentialsPath, scopes } = loggedIn
    return { status: 'logged_in', host, projectId, credentialsPath, next: nextCommand(scopes) }
}

async function finish(ctx: Context, pending: PendingLogin, spinner?: Spinner): Promise<LoginResult> {
    let loggedIn
    try {
        loggedIn = await completeLogin(ctx.runtime, pending)
    } catch (error) {
        spinner?.error("The login didn't finish")
        throw error
    }
    spinner?.stop('Approved')
    return loggedInResult(loggedIn)
}

async function keyLogin(ctx: Context, prompts: Prompts): Promise<LoginResult> {
    const host = await prompts.text('PostHog host', { initialValue: REGIONS.us, validate: checkHost })
    const projectId = await prompts.text('Project ID, the number in your project URL', { validate: checkProjectId })
    const apiKey = await prompts.password('Personal API key', { validate: checkApiKey })
    return loggedInResult(await saveLogin(ctx.runtime, { apiKey, projectId, host: host.replace(/\/+$/, '') }))
}

export default defineCommand({
    description: 'Log in to PostHog and store a personal API key on this machine',
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
        'In CI, skip login and set HOG_API_KEY, HOG_PROJECT_ID and HOG_HOST.',
    ].join('\n'),
    examples: ['hog auth login', 'hog auth login --region eu', 'hog auth login --wait'],

    async run({ options, ctx }): Promise<LoginResult> {
        const { env } = ctx.runtime
        const prompts = ctx.prompts

        if (options.wait) {
            const pending = await readPendingLogin(ctx.runtime)
            if (!pending) {
                throw new HogError(
                    'no_pending_login',
                    'No login is waiting for approval.',
                    'Run `hog auth login` to start one.'
                )
            }
            return finish(ctx, pending, prompts?.spinner('Waiting for the login to be approved in the browser'))
        }

        if (!prompts && ctx.mode.agent === undefined && isTruthy(env.CI)) {
            throw new HogError(
                'login_needs_a_person',
                'hog auth login needs a person to approve it in a browser, so it does not run in CI.',
                'Set HOG_API_KEY, HOG_PROJECT_ID and HOG_HOST instead.'
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

        const pending = await startLogin(ctx.runtime, host)

        if (!prompts) {
            return pendingResult(pending)
        }
        prompts.note(`${pending.url}\n\nCode: ${escapeControls(pending.userCode)}`, 'Approve the login in your browser')
        // Over SSH, a browser would open on the remote machine, where nobody sees it.
        const overSsh = env.SSH_CONNECTION !== undefined || env.SSH_TTY !== undefined
        const opened = !overSsh && (await ctx.runtime.openUrl(pending.url))
        return finish(
            ctx,
            pending,
            prompts.spinner(
                opened ? 'Waiting for you to approve in the browser' : 'Open the link above to approve. Waiting'
            )
        )
    },

    human({ result, out }) {
        if (result.status === 'pending') {
            out.line(
                `Open this link to approve the login, and check that it shows the code ${out.style(escapeControls(result.code), 'bold')}:`
            )
            out.line(`  ${result.url}`)
            out.line(`Then run ${out.style(result.next, 'bold')}.`)
            return
        }
        out.line(`${out.style('Logged in', 'green', 'bold')} to ${result.host}, project ${result.projectId}.`)
        out.line(out.style(`Credentials saved to ${result.credentialsPath}`, 'dim'))
        out.line(`Try it: ${result.next}`)
    },
})
