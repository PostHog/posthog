import { z } from 'zod'

import { SIGN_UP_NOTE } from '@/core/approval'
import { defineCommand, type OptionSpec } from '@/core/command'
import { EXIT_NEEDS_PERSON, EXIT_SUCCESS, EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls, type Output } from '@/core/output'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { plural } from '@/core/text'
import { REGION_IDS } from '@/posthog/host'
import { PRODUCT_IDS, ProductListSchema } from '@/setup/products'
import type { NextAction, SetupResult } from '@/setup/result'

const Reason = z
    .string()
    .trim()
    .min(1, { error: 'Pass a few words on what the user wants to use PostHog for.' })
    .max(1000, { error: 'Keep the reason under 1000 characters.' })

const PRODUCTS_HINT = `Pass product IDs separated by commas: ${PRODUCT_IDS.join(', ')}.`

const OPTIONS = {
    reason: {
        type: 'string',
        placeholder: 'text',
        parse: (raw: string, failure: ParseFailure) => parseOrThrow(Reason, raw, failure),
        description:
            'What the project uses PostHog for, from the conversation or the code. hog sends it to PostHog unless telemetry is off',
    },
    products: {
        type: 'string',
        placeholder: 'ids',
        parse: (raw: string, failure: ParseFailure) =>
            parseOrThrow(ProductListSchema, raw, { ...failure, hint: PRODUCTS_HINT }),
        description: `Product IDs that match the reason, separated by commas: ${PRODUCT_IDS.join(', ')}`,
    },
    region: {
        type: 'string',
        choices: REGION_IDS,
        placeholder: 'region',
        description:
            'Where PostHog hosts your data, when `posthog.json` has no host. Defaults to `us`. Pass `eu` when the user mentions the EU or data residency',
    },
    reviewed: {
        type: 'boolean',
        description: 'You checked your changes against the install rules and fixed any that break one',
    },
} as const satisfies Record<string, OptionSpec>

const AGENT_LEADING_KEYS = ['step', 'status', 'code', 'next', 'done'] as const

function agentResult(result: SetupResult): unknown {
    const { skills } = result.context
    return skills ? { ...result, context: { ...result.context, skills: skills.map((skill) => skill.id) } } : result
}

function joinBlocks(blocks: readonly (readonly string[])[]): string[] {
    return blocks.filter((lines) => lines.length > 0).flatMap((lines, index) => (index === 0 ? lines : ['', ...lines]))
}

function contextLines(out: Output, result: SetupResult): string[][] {
    const { token, apiHost, events, products = [], skills = [], agentsMd = [], mcp } = result.context
    const finished = result.status === 'connected' && products.length > 0

    return [
        token && apiHost ? [`Project token: ${escapeControls(token)}`, `Host for the SDK: ${apiHost}`] : [],
        events?.count != null && events.count > 0 ? [`${plural(events.count, 'event')} since ${events.since}`] : [],
        finished
            ? [
                  out.style('What else PostHog can do:', 'bold'),
                  ...products.map(
                      ({ label, description, command }) =>
                          `  ${label}: ${description} ${out.style(escapeControls(command), 'dim')}`
                  ),
              ]
            : [],
        finished && skills.length > 0
            ? [
                  out.style('Skills you can add later with hog skills add <skill...>:', 'bold'),
                  ...skills.map((skill) => `  ${escapeControls(skill.id)}: ${escapeControls(skill.description)}`),
              ]
            : [],
        finished && mcp && !mcp.configured
            ? [
                  mcp.foreign
                      ? `The posthog MCP server in ${escapeControls(mcp.foreign.path)} points at another server. Run ${out.style(mcp.command, 'bold')} to replace it with PostHog's.`
                      : `Connect PostHog's MCP server to your agent with ${out.style(mcp.command, 'bold')}`,
              ]
            : [],
        result.status === 'connected'
            ? agentsMd.map((file) => out.style(`The PostHog section is in ${escapeControls(file.path)}`, 'dim'))
            : [],
    ]
}

function nextLines(out: Output, next: NextAction): [string, ...string[]] {
    const setupNext = out.style('hog setup', 'bold')

    switch (next.kind) {
        case 'wait':
            return [
                `Open this link and approve the code ${out.style(escapeControls(next.code ?? ''), 'bold')}. ${SIGN_UP_NOTE} Then run ${setupNext}.`,
                `  ${escapeControls(next.url)}`,
            ]
        case 'read':
            return [escapeControls(next.instructions), ...next.read.map((command) => `  ${out.style(command, 'bold')}`)]
        case 'run':
            return [escapeControls(next.instructions), `  ${out.style(next.command, 'bold')}`]
        case 'done':
            return [escapeControls(next.instructions)]
    }
}

function nextBlock(out: Output, result: SetupResult): string[] {
    const [first, ...rest] =
        result.step === 'purpose'
            ? [`Run ${out.style('hog setup', 'bold')} to say what you want to use PostHog for.`]
            : nextLines(out, result.next)
    return [`${out.style('Next:', 'bold')} ${first}`, ...rest]
}

// The lines below are for a person at a terminal. The instructions in the result are for an agent.
function printSetup(out: Output, result: SetupResult, ranSteps: boolean): void {
    const { context } = result
    const folder = escapeControls(context.folder)
    const warnings = [
        ...(result.status === 'connected' && !context.loggedIn ? ['Not logged in'] : []),
        ...context.warnings.map(escapeControls),
        ...(context.events?.count === 0 ? [`No events since ${context.events.since}`] : []),
    ]
    const notes = joinBlocks([...contextLines(out, result), nextBlock(out, result)])

    if (result.status === 'connected') {
        out.report({
            status: context.loggedIn ? 'done' : 'partial',
            result: `PostHog is set up in ${folder}`,
            effects: [
                `Project ${context.projectId ?? 'unknown'} on ${escapeControls(context.host ?? 'an unknown host')}`,
                ...(context.loggedIn ? ['Logged in'] : []),
            ],
            warnings,
            notes,
        })
        return
    }

    out.report({
        status: ranSteps ? 'partial' : 'unchanged',
        result: `PostHog setup in ${folder} isn't finished`,
        effects: result.done.map((step) => `${out.style('Done', 'green')}  ${escapeControls(step.summary)}`),
        warnings,
        notes,
    })
}

export default defineCommand({
    description: 'Set up PostHog in this folder, one step at a time',
    args: {
        action: {
            description: '`status` shows the current step and changes nothing',
            optional: true,
        },
    },
    options: OPTIONS,
    writes: true,
    refusesCI: {
        reason: 'sets up a folder with a person',
        hint: 'Run `hog setup` on your machine and commit what it writes. To let a CI job use hog, run `hog ci setup` on your machine.',
    },
    scopes: ['project:read', 'query:read'],
    notes: [
        '`hog setup` guides you through setting up PostHog step by step. It does the current step and keeps going until a step needs you or your agent. Its output names that step and what to do before you run it again.',
        '`hog setup status` shows the current step and changes nothing.',
        'The setup belongs to the folder of the closest posthog.json, or to this folder when there is none, so each app in a monorepo has its own.',
        'An agent works out the answers from the conversation and the code, and passes them as options. It runs `hog setup` again only when a step stops.',
    ].join('\n'),
    examples: [
        'hog setup',
        'hog setup --reason "See where users drop off" --products product-analytics,session-replay',
        'hog setup --reason "Track errors in our EU app" --products error-tracking --region eu',
        'hog setup --reviewed',
        'hog setup status',
    ],

    async run({ args, options, ctx }): Promise<SetupResult> {
        if (args.action !== undefined && args.action !== 'status') {
            throw new HogError(
                'invalid_setup_command',
                `There is no \`hog setup ${escapeControls(args.action)}\`.`,
                '`hog setup` guides you through setting up PostHog step by step, and stops whenever it needs you or your agent. Run it to go on, or run `hog setup status` to see where you are.',
                EXIT_USAGE
            )
        }

        const next = args.action !== 'status'
        const given = Object.values(options).some((value) => value !== undefined && value !== false)
        if (!next && given) {
            throw new HogError(
                'setup_status_takes_no_options',
                '`hog setup status` takes no options.',
                'Run `hog setup` with the same options.',
                EXIT_USAGE
            )
        }

        const { requireLatestForSetup } = await import('@/updates/check')
        const hog = await requireLatestForSetup(
            ctx.runtime,
            next ? 'setup' : 'setup status',
            ctx.globals.skipSslVerification === true
        )

        const { runSetup } = await import('@/setup/run')
        return { ...(await runSetup(ctx, { next, ...options })), hog }
    },

    human({ args, result, out }) {
        printSetup(out, result, args.action !== 'status')
    },

    agent({ result, out }) {
        out.json(agentResult(result), { first: AGENT_LEADING_KEYS })
    },

    // The agent does `run` and `read` itself, so only an approval waits on the person.
    exitCode: (result) => (result.next.kind === 'wait' ? EXIT_NEEDS_PERSON : EXIT_SUCCESS),

    telemetry: ({ args, result }) => ({
        setup_action: args.action ?? 'run',
        setup_step: result.step,
        setup_status: result.status,
        setup_code: result.code,
    }),
})
