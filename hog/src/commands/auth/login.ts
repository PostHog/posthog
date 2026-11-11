import { dirname } from 'node:path'

import { printPending, refuseInCi, resumeApproval, runApproval, type PendingResult } from '@/core/approval'
import { defineCommand } from '@/core/command'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import type { Prompts } from '@/core/prompts'
import { validationError } from '@/core/schema'
import { PersonalAPIKey, type AccessKey } from '@/posthog/access-key'
import { CI_CREDENTIALS_HINT } from '@/posthog/credentials'
import { LOGIN_SCOPES, READ_ONLY_LOGIN_SCOPES } from '@/posthog/device-auth'
import { cloudRegion, HostSchema, parseHost, REGION_CHOICES, REGION_IDS, REGIONS } from '@/posthog/host'
import { parseProjectId, ProjectIdSchema } from '@/posthog/ids'
import { finishLogin, type FinishedLogin } from '@/posthog/login/finish'
import { LOGIN_COMMAND, loginFlow, loginWait } from '@/posthog/login/flow'
import { parsePersonalApiKey, PersonalApiKeySchema } from '@/posthog/tokens'

type LoginResult = (PendingResult & { host: string }) | (FinishedLogin & { next: string })

function nextCommand(scopes: readonly string[] | null): string {
    const canQuery = scopes?.some((scope) => scope === '*' || scope.startsWith('query:')) ?? false
    return canQuery ? 'hog query run "select event, count() from events group by event"' : 'hog --help'
}

async function finish(ctx: Context, key: AccessKey): Promise<LoginResult> {
    const finished = await finishLogin(ctx, key)
    return { ...finished, next: nextCommand(finished.scopes) }
}

async function keyLogin(ctx: Context, prompts: Prompts): Promise<LoginResult> {
    const host = await prompts.text('PostHog host', {
        initialValue: REGIONS.us,
        validate: (value) => validationError(HostSchema, value),
    })
    const projectId = await prompts.text('Project ID, the number in your project URL', {
        validate: (value) => validationError(ProjectIdSchema, value),
    })
    const apiKey = await prompts.password('Personal API key', {
        validate: (value) => validationError(PersonalApiKeySchema, value),
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
            choices: REGION_IDS,
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
                'Ask only for read access. To change something later, run `hog auth add` with the write scopes you need',
        },
    },
    notes: [
        'At a terminal, hog asks where your PostHog account is hosted and opens the browser to approve the login.',
        'Agents and scripts get a link and a code to hand to a person, then finish with `hog auth login --wait`.',
        'You pick one project when you approve the login, and the token only works in that project. The token renews automatically.',
        'Each project has its own login, and the closest posthog.json picks the one a command uses. Login writes the host and project to posthog.json in this folder, or to the closest one above it.',
        'hog stores the token in the system keychain. If no keychain is available, such as over SSH, it stores the token in a file only you can read.',
        'In CI, skip login. Run `hog ci setup` once so jobs use their OIDC token, or set HOG_PERSONAL_API_KEY and HOG_HOST, with the project ID in posthog.json as "projectId" or in HOG_PROJECT_ID.',
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
            return finish(ctx, (await resumeApproval(ctx, loginWait(ctx.runtime))).value)
        }

        refuseInCi(ctx, LOGIN_COMMAND, CI_CREDENTIALS_HINT)

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
                    ...REGION_CHOICES,
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

        const { path, status, error } = result.config
        const file = escapeControls(path)
        if (status === 'failed') {
            out.line(
                out.style(
                    `hog couldn't write ${file}: ${escapeControls(error ?? '').replace(/\.?$/, '.')} Add "host": "${escapeControls(result.host)}" and "projectId": ${result.projectId} to it, so commands there use this login.`,
                    'yellow'
                )
            )
            out.line(`Try it: ${result.next}`)
            return
        }

        const saved = {
            created: `Created ${file} with this host and project.`,
            updated: `Set this host and project in ${file}.`,
            unchanged: `${file} already names this host and project.`,
        }[status]
        out.line(saved)
        out.line(
            out.style(
                `Commands under ${escapeControls(dirname(path))} use this login, unless a closer posthog.json names another project.`,
                'dim'
            )
        )
        out.line(`Try it: ${result.next}`)
    },
})
