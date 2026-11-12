import { z } from 'zod'

import { defineCommand, type OptionSpec } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
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
            'What the user wants to use PostHog for, in their words. hog sends it to PostHog unless telemetry is off',
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

// Agent tools often keep only the start of a long output, so the outcome comes before `context`.
const AGENT_LEADING_KEYS = ['step', 'status', 'code', 'next', 'done'] as const

// Agents get skill names only, as `hog skills list` gives them. `hog skills search` describes them.
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
    const setupNext = out.style('hog setup next', 'bold')

    switch (next.kind) {
        case 'ask_user':
            return [`Run ${setupNext} to answer this question at the terminal.`, `  ${escapeControls(next.ask)}`]
        case 'wait':
            return [
                `Open this link and approve the code ${out.style(escapeControls(next.code ?? ''), 'bold')}. If you don't have an account, sign up on the same page. Then run ${setupNext}.`,
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

function nextBlock(out: Output, next: NextAction): string[] {
    const [first, ...rest] = nextLines(out, next)
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
    const notes = joinBlocks([...contextLines(out, result), nextBlock(out, result.next)])

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
            description: '`next` runs the current step and every later step that needs no input',
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
        '`hog setup` shows the current step and what `hog setup next` will do, and changes nothing.',
        '`hog setup next` does the current step and keeps going until a step needs you or your agent. Its output names that step.',
        'The setup belongs to the folder of the closest posthog.json, or to this folder when there is none, so each app in a monorepo has its own.',
        "An agent passes the answers as options and asks the user only what it can't tell. It runs `hog setup next` again only when a step stops.",
    ].join('\n'),
    examples: [
        'hog setup',
        'hog setup next',
        'hog setup next --reason "See where users drop off" --products product-analytics,session-replay',
        'hog setup next --reason "Track errors in our EU app" --products error-tracking --region eu',
        'hog setup next --reviewed',
    ],

    async run({ args, options, ctx }): Promise<SetupResult> {
        if (args.action !== undefined && args.action !== 'next') {
            throw new HogError(
                'invalid_setup_command',
                `There is no \`hog setup ${escapeControls(args.action)}\`.`,
                'Run `hog setup` to see the current step, or `hog setup next` to run it.',
                EXIT_USAGE
            )
        }

        const next = args.action === 'next'
        const given = Object.values(options).some((value) => value !== undefined && value !== false)
        if (!next && given) {
            throw new HogError(
                'setup_options_need_next',
                'These options only work with `hog setup next`.',
                'Run `hog setup next` with the same options.',
                EXIT_USAGE
            )
        }

        const { runSetup } = await import('@/setup/run')
        return runSetup(ctx, { next, ...options })
    },

    human({ args, result, out }) {
        printSetup(out, result, args.action === 'next')
    },

    agent({ result, out }) {
        out.json(agentResult(result), { first: AGENT_LEADING_KEYS })
    },

    telemetry: ({ args, result }) => ({
        setup_action: args.action ?? 'status',
        setup_step: result.step,
        setup_status: result.status,
        setup_code: result.code,
    }),
})
