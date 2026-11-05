import { printPending, resumeApproval, runApproval, type ApprovalResult } from '@/core/approval'
import { defineCommand } from '@/core/command'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import type { Prompts } from '@/core/prompts'
import { problemWith } from '@/core/schema'
import { PersonalAPIKey, type AccessKey } from '@/posthog/access-key'
import type { StoreChoice } from '@/posthog/credential-store/types'
import { LOGIN_SCOPES, READ_ONLY_LOGIN_SCOPES } from '@/posthog/device-auth'
import { hostKey, HostSchema, parseHost, type Host } from '@/posthog/host'
import { parseProjectId, ProjectIdSchema } from '@/posthog/ids'
import { loginFlow, loginWait, saveLogin, type LoggedIn } from '@/posthog/login/flow'
import { parsePersonalApiKey, PersonalApiKeySchema } from '@/posthog/tokens'

const REGIONS = { us: parseHost('https://us.posthog.com'), eu: parseHost('https://eu.posthog.com') }

// A posthog.json comes with the repository, so it only picks between the PostHog Cloud regions. A
// login to any other host needs --host, so a repository can't send a person's login elsewhere.
function cloudRegion(host: Host | undefined): Host | undefined {
    return host && Object.values(REGIONS).find((region) => hostKey(region) === hostKey(host))
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
          // What the login may do, as PostHog reports it.
          scopes: string[] | null
          // ISO 8601, for an OAuth login. hog renews the token before then.
          expiresAt: string | null
          next: string
      }

function nextCommand(scopes: readonly string[] | null): string {
    const canQuery = scopes?.some((scope) => scope === '*' || scope.startsWith('query:')) ?? false
    return canQuery ? 'hog query run "select event, count() from events group by event"' : 'hog --help'
}

function loggedInResult(loggedIn: LoggedIn): LoginResult {
    const { host, projectId, store, credentialsPath, keychainError, status } = loggedIn
    const { scopes, expiresAt } = status
    return {
        status: 'logged_in',
        host,
        projectId,
        store,
        credentialsPath,
        keychainError,
        scopes,
        expiresAt: expiresAt === null ? null : new Date(expiresAt).toISOString(),
        next: nextCommand(scopes),
    }
}

async function finish(ctx: Context, key: AccessKey): Promise<LoginResult> {
    return loggedInResult(await saveLogin(ctx.runtime, key))
}

async function keyLogin(ctx: Context, prompts: Prompts): Promise<LoginResult> {
    const host = await prompts.text('PostHog host', {
        initialValue: REGIONS.us,
        validate: (value) => problemWith(HostSchema, value),
    })
    const projectId = await prompts.text('Project ID, the number in your project URL', {
        validate: (value) => problemWith(ProjectIdSchema, value),
    })
    const apiKey = await prompts.password('Personal API key', {
        validate: (value) => problemWith(PersonalApiKeySchema, value),
    })
    const key = new PersonalAPIKey({
        host: parseHost(host),
        projectId: parseProjectId(projectId),
        apiKey: parsePersonalApiKey(apiKey),
    })
    return finish(ctx, key)
}

export default defineCommand({
    description: 'Log in to PostHog in the browser',
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
            description: 'Wait for the login an agent or script started, and save the token once a person approves it',
        },
        readOnly: {
            type: 'boolean',
            description:
                'Ask only for read access. To change something later, run `hog auth login` again without this flag',
        },
    },
    notes: [
        'At a terminal, hog asks where your PostHog account is hosted and opens the browser to approve the login.',
        'Agents and scripts get a link and a code to hand to a person, then finish with `hog auth login --wait`.',
        'The person picks one project, and the token only works there. To use another project, log in again. hog renews the token by itself.',
        'hog stores the token in the system keychain. If no keychain is available, such as over SSH, it stores the token in a file only you can read.',
        'In CI, skip login and set HOG_PERSONAL_API_KEY, HOG_PROJECT_ID and HOG_HOST.',
    ].join('\n'),
    examples: ['hog auth login', 'hog auth login --region eu', 'hog auth login --read-only', 'hog auth login --wait'],

    async run({ options, ctx }): Promise<LoginResult> {
        const prompts = ctx.prompts

        if (options.wait && options.readOnly) {
            throw new HogError(
                'read_only_with_wait',
                '--read-only sets what a new login asks for, and --wait finishes the login that already started.',
                'Run `hog auth login --read-only` to start a read-only login, then `hog auth login --wait`.',
                EXIT_USAGE
            )
        }
        if (options.wait) {
            return finish(ctx, await resumeApproval(ctx, loginWait(ctx.runtime)))
        }

        if (!prompts && ctx.mode.agent === undefined && ctx.mode.ci) {
            throw new HogError(
                'login_needs_a_person',
                'hog auth login needs a person to approve it in a browser, so it does not run in CI.',
                'Set HOG_PERSONAL_API_KEY, HOG_PROJECT_ID and HOG_HOST instead.'
            )
        }

        let host =
            ctx.globals.host ??
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
                if (options.readOnly) {
                    throw new HogError(
                        'read_only_with_key',
                        "--read-only can't limit a personal API key: the key keeps the scopes it has in PostHog.",
                        'Approve a read-only login in the browser instead, or create a key with read scopes only.',
                        EXIT_USAGE
                    )
                }
                return keyLogin(ctx, prompts)
            }
            host = REGIONS[choice]
        }

        const scopes = options.readOnly ? READ_ONLY_LOGIN_SCOPES : LOGIN_SCOPES
        const result = await runApproval(ctx, loginFlow(ctx.runtime, host, scopes))
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
