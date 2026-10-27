import { defineCommand } from '@/core/command'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import type { Prompts, Spinner } from '@/core/prompts'
import { checkApiKey, checkHost, checkProjectId, posthogFile, saveCredentials } from '@/posthog/credentials'
import { PENDING_LOGIN_FILE, startDeviceLogin, waitForApproval, type PendingLogin } from '@/posthog/device-auth'

const REGIONS = { us: 'https://us.posthog.com', eu: 'https://eu.posthog.com' } as const

const REUSE_MARGIN_MS = 60_000

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

async function readPending(ctx: Context): Promise<PendingLogin | undefined> {
    try {
        return JSON.parse(await ctx.runtime.readFile(posthogFile(ctx.runtime, PENDING_LOGIN_FILE))) as PendingLogin
    } catch {
        return undefined
    }
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

async function finish(ctx: Context, pending: PendingLogin, spinner?: Spinner): Promise<LoginResult> {
    const pendingPath = posthogFile(ctx.runtime, PENDING_LOGIN_FILE)
    let approval
    try {
        approval = await waitForApproval(ctx.runtime, pending)
    } catch (error) {
        spinner?.error("The login didn't finish")
        if (error instanceof HogError && error.code !== 'network_error') {
            await ctx.runtime.removeFile(pendingPath)
        }
        throw error
    }
    const credentialsPath = await saveCredentials(ctx.runtime, {
        apiKey: approval.apiKey,
        projectId: approval.projectId,
        host: pending.host,
    })
    await ctx.runtime.removeFile(pendingPath)
    spinner?.stop('Approved')
    return {
        status: 'logged_in',
        host: pending.host,
        projectId: approval.projectId,
        credentialsPath,
        next: nextCommand(approval.scopes),
    }
}

async function keyLogin(ctx: Context, prompts: Prompts): Promise<LoginResult> {
    const host = await prompts.text('PostHog host', { initialValue: REGIONS.us, validate: checkHost })
    const projectId = await prompts.text('Project ID, the number in your project URL', { validate: checkProjectId })
    const apiKey = await prompts.password('Personal API key', { validate: checkApiKey })
    const normalizedHost = host.replace(/\/+$/, '')
    const credentialsPath = await saveCredentials(ctx.runtime, { apiKey, projectId, host: normalizedHost })
    return { status: 'logged_in', host: normalizedHost, projectId, credentialsPath, next: nextCommand([]) }
}

export default defineCommand({
    description: 'Log in to PostHog and store a personal API key on this machine',
    options: {
        region: {
            type: 'string',
            choices: ['us', 'eu'],
            placeholder: 'region',
            description: 'The PostHog Cloud region to log in to. Use --host for self-hosted PostHog',
        },
        wait: {
            type: 'boolean',
            description: 'Wait for the login an agent or script started, and save the key once a person approves it',
        },
    },
    notes: [
        'At a terminal, hog asks for your region and opens the browser to approve the login.',
        'Agents and scripts get a link and a code to hand to a person, then finish with `hog auth login --wait`.',
        'In CI, skip login and set POSTHOG_CLI_API_KEY, POSTHOG_CLI_PROJECT_ID and POSTHOG_CLI_HOST.',
    ].join('\n'),
    examples: ['hog auth login', 'hog auth login --region eu', 'hog auth login --wait'],

    async run({ options, ctx }): Promise<LoginResult> {
        const { env } = ctx.runtime
        const prompts = ctx.prompts

        if (options.wait) {
            const pending = await readPending(ctx)
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
                'Set POSTHOG_CLI_API_KEY, POSTHOG_CLI_PROJECT_ID and POSTHOG_CLI_HOST instead.'
            )
        }

        let host = ctx.globals.host?.replace(/\/+$/, '') ?? (options.region ? REGIONS[options.region] : undefined)
        if (!host) {
            if (!prompts) {
                throw new HogError(
                    'region_required',
                    'hog auth login needs to know which PostHog to log in to.',
                    'Ask the user whether their PostHog is in the US or EU cloud, then run `hog auth login --region us` or `hog auth login --region eu`. For self-hosted PostHog, pass --host.',
                    EXIT_USAGE
                )
            }
            const choice = await prompts.select('Where is your PostHog?', [
                { value: 'us', label: 'US Cloud', hint: 'us.posthog.com' },
                { value: 'eu', label: 'EU Cloud', hint: 'eu.posthog.com' },
                {
                    value: 'key',
                    label: 'Paste a personal API key',
                    hint: 'for self-hosted PostHog, or without a browser',
                },
            ])
            if (choice === 'key') {
                return keyLogin(ctx, prompts)
            }
            host = REGIONS[choice]
        }

        // Retrying agents get the same code back, so the link they already shared keeps working.
        const existing = await readPending(ctx)
        const pending =
            existing?.host === host && existing.expiresAt - ctx.runtime.now() > REUSE_MARGIN_MS
                ? existing
                : await startDeviceLogin(ctx.runtime, host)
        await ctx.runtime.writePrivateFile(posthogFile(ctx.runtime, PENDING_LOGIN_FILE), JSON.stringify(pending))

        if (!prompts) {
            return pendingResult(pending)
        }
        prompts.note(`${pending.url}\n\nCode: ${pending.userCode}`, 'Approve the login in your browser')
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
                `Open this link to approve the login, and check that it shows the code ${out.style(result.code, 'bold')}:`
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
