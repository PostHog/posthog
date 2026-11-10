import { z } from 'zod'

import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls, type Output } from '@/core/output'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { plural } from '@/core/text'
import { REGION_IDS } from '@/posthog/host'
import type { SetupResult } from '@/setup/run'

const Reason = z
    .string()
    .trim()
    .min(1, { error: 'Write why you are adding PostHog, in a few words.' })
    .max(1000, { error: 'Keep the reason under 1000 characters.' })

const IdList = z
    .string()
    .transform((raw) =>
        raw
            .split(',')
            .map((id) => id.trim().toLowerCase())
            .filter(Boolean)
    )
    .pipe(z.array(z.string().regex(/^[a-z0-9-]+$/, { error: 'Use ids like product-analytics.' })).min(1))

const ProductList = z.union([z.literal('none').transform((): string[] => []), IdList])

const NEXT_OPTIONS = ['reason', 'products', 'region', 'reviewed', 'productsAck', 'installSkills'] as const

// The instructions address an agent. A person who asks or approves gets their own line here.
function printNext(out: Output, result: SetupResult): void {
    const { next } = result
    const forPerson =
        next.kind === 'ask_user'
            ? `Run ${out.style('hog setup next', 'bold')} to answer ${next.ask.length === 1 ? 'this question' : 'these questions'} at the terminal.`
            : next.kind === 'wait'
              ? `Open this link and approve the code ${out.style(escapeControls(next.code ?? ''), 'bold')}. New users can sign up on the same page. Then run ${out.style('hog setup next', 'bold')}.`
              : escapeControls(next.instructions)
    out.line()
    out.line(`${out.style('Next:', 'bold')} ${forPerson}`)
    switch (next.kind) {
        case 'run':
            out.line(`  ${out.style(next.command, 'bold')}`)
            return
        case 'read':
            for (const command of next.read) {
                out.line(`  ${out.style(command, 'bold')}`)
            }
            return
        case 'wait':
            out.line(`  ${escapeControls(next.url)}`)
            return
        case 'ask_user':
            for (const question of next.ask) {
                out.line(`  ${escapeControls(question.question)}`)
                for (const choice of question.choices ?? []) {
                    out.line(out.style(`    ${choice.value}: ${escapeControls(choice.label)}`, 'dim'))
                }
            }
            return
        case 'done':
            return
    }
}

function printProducts(out: Output, result: SetupResult): void {
    const products = result.context.products ?? []
    if (products.length === 0) {
        return
    }
    out.line()
    out.line(out.style('What else PostHog can do:', 'bold'))
    for (const product of products) {
        const about = product.description ? ` ${escapeControls(product.description)}` : ''
        out.line(`  ${escapeControls(product.label)}:${about} ${out.style(escapeControls(product.command), 'dim')}`)
    }
}

function printSummary(out: Output, result: SetupResult): void {
    const { context } = result
    out.line(`${out.style('PostHog is set up', 'green', 'bold')} in ${escapeControls(context.folder)}.`)
    out.line(`Project ${context.projectId ?? 'unknown'} on ${escapeControls(context.host ?? 'an unknown host')}`)
    out.line(context.loggedIn ? 'Logged in' : out.style('Not logged in', 'yellow'))
    const events = context.events
    if (events?.count !== null && events?.count !== undefined) {
        out.line(`${plural(events.count, 'event')} since ${events.since}`)
    }
    for (const file of context.agentsMd ?? []) {
        out.line(out.style(`The PostHog note is in ${escapeControls(file.path)}`, 'dim'))
    }
}

export default defineCommand({
    description: 'Set up PostHog in this folder, one step at a time',
    args: {
        action: {
            description: '`next` does the current step and every step after it that hog can do alone',
            optional: true,
        },
    },
    options: {
        reason: {
            type: 'string',
            placeholder: 'text',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(Reason, raw, failure),
            description:
                'Why you are adding PostHog, in your own words. hog sends it to PostHog unless telemetry is off',
        },
        products: {
            type: 'string',
            placeholder: 'ids',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(ProductList, raw, failure),
            description: 'The products that interest you, separated by commas, or none. `hog setup` lists them',
        },
        region: {
            type: 'string',
            choices: REGION_IDS,
            placeholder: 'region',
            description: 'Where to host your PostHog data, when posthog.json names no host',
        },
        reviewed: {
            type: 'boolean',
            description: 'You checked your changes against the install rules and fixed any that broke one',
        },
        productsAck: {
            type: 'boolean',
            description: 'You went through the other products, and the setup can finish',
        },
        installSkills: {
            type: 'string',
            placeholder: 'ids',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(IdList, raw, failure),
            description:
                'Install these PostHog skills into the repository at the products step, separated by commas. Also finishes that step',
        },
    },
    writes: true,
    scopes: ['project:read', 'query:read'],
    notes: [
        '`hog setup` shows the current step and what `hog setup next` will do, and changes nothing.',
        '`hog setup next` does the current step and keeps going until a step needs you or your agent. Its output names that step.',
        'The setup belongs to the folder of the closest posthog.json, or to this folder when there is none, so each app in a monorepo has its own.',
        'Agents pass the answers as options, and finish a browser login with another `hog setup next`.',
    ].join('\n'),
    examples: [
        'hog setup',
        'hog setup next',
        'hog setup next --reason "See where users drop off" --products product-analytics,session-replay --region us',
        'hog setup next --reviewed',
        'hog setup next --products-ack',
    ],

    async run({ args, options, ctx }): Promise<SetupResult> {
        if (args.action !== undefined && args.action !== 'next') {
            throw new HogError(
                'invalid_setup_command',
                `hog setup has no \`${escapeControls(args.action)}\`.`,
                'Run `hog setup` to see the current step, or `hog setup next` to do it.',
                EXIT_USAGE
            )
        }
        const next = args.action === 'next'
        const given = NEXT_OPTIONS.filter((name) => options[name] !== undefined && options[name] !== false)
        if (!next && given.length > 0) {
            throw new HogError(
                'setup_options_need_next',
                'These options go with `hog setup next`.',
                `Run \`hog setup next\` with them instead of \`hog setup\`.`,
                EXIT_USAGE
            )
        }
        const { runSetup } = await import('@/setup/run')
        return runSetup(ctx, { next, ...options })
    },

    human({ result, out }) {
        if (result.status === 'connected') {
            printSummary(out, result)
            printProducts(out, result)
            printNext(out, result)
            return
        }
        out.line(`Setting up PostHog in ${escapeControls(result.context.folder)}`)
        for (const step of result.done) {
            out.line(`${out.style('Done', 'green')}  ${escapeControls(step.summary)}`)
        }
        for (const warning of result.context.warnings) {
            out.line(out.style(escapeControls(warning), 'yellow'))
        }
        const { token, apiHost } = result.context
        if (token && apiHost) {
            out.line()
            out.line(`Project token: ${token}`)
            out.line(`Host for the SDK: ${apiHost}`)
        }
        if (result.step === 'products') {
            printProducts(out, result)
        }
        printNext(out, result)
    },

    agent({ result, out }) {
        out.json(result)
    },

    // `hog setup next` checked for events and found none. At the verify step, `hog setup` only
    // describes the check, so its count stays null and it exits 0.
    exitCode: (result) => (result.code === 'setup_no_events_yet' && result.context.events?.count === 0 ? 1 : 0),

    telemetry: ({ args, result }) => ({
        setup_action: args.action ?? 'status',
        setup_step: result.step,
        setup_status: result.status,
        setup_code: result.code,
    }),
})
