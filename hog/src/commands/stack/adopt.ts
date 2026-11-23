import { z } from 'zod'

import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { checkStack } from '@/stack/check'
import { resolveStack, stackOptions } from '@/stack/config'
import { selectorFlags, shellWord } from '@/stack/diff'
import { stackService } from '@/stack/service'

const Kind = z.string().regex(/^[a-z][a-z0-9_]*$/, 'Use a definition kind such as flag or event.')
const Key = z
    .string()
    .min(1)
    .max(512)
    .regex(/^[^\p{Cc}]+$/u, 'Use the key the definition has in the stack.')
const EntityId = z
    .string()
    .min(1)
    .max(512)
    .regex(/^[^\s\p{Cc}]+$/u, 'Use the entity ID PostHog shows.')
const parse =
    <T>(schema: z.ZodType<T, string>) =>
    (raw: string, failure: ParseFailure) =>
        parseOrThrow(schema, raw, failure)

// The service's codes, with hints for binding an entity to a definition that is already in code.
const hints: Readonly<Record<string, string>> = {
    entity_not_found: 'Check the ID in PostHog, or the ID a hog diff warning lists, and that you can edit that entity.',
    entity_already_bound: 'This entity already has a binding. Run hog diff to see which definition manages it.',
    key_already_bound:
        'This definition is already bound to another entity. Run hog diff to review it, or bind the entity to a different definition.',
    claimed_by_other_stack:
        'Another stack manages this entity. Edit its definition there, or release it in that stack first.',
}

export default defineCommand({
    description:
        'Bind an existing entity to a definition the stack already has, so the next push takes it over and creates nothing',
    args: {
        kind: { description: 'The definition kind, such as flag or event' },
        key: { description: 'The key of the definition in the stack' },
        entityId: { description: 'The ID of the entity in PostHog' },
    },
    options: stackOptions,
    scopes: ['stack:write'],
    writes: true,
    notes: 'Use it when the definition is already in the folder, as after a push that stopped without a known outcome. To bring an entity with no definition into code, use hog pull --adopt instead, which writes the definition. Nothing changes in PostHog until the next push, so review it with hog diff first.',
    examples: ['hog stack adopt flag new-checkout 4211'],

    async run({ ctx, args, options }) {
        const kind = parse(Kind)(args.kind, {
            code: 'invalid_kind',
            exitCode: EXIT_USAGE,
            hint: 'Pass the kind the definition has, such as flag.',
        })
        const key = parse(Key)(args.key, {
            code: 'invalid_key',
            exitCode: EXIT_USAGE,
            hint: 'Pass the key the definition has in the stack.',
        })
        const entityId = parse(EntityId)(args.entityId, {
            code: 'invalid_entity_id',
            exitCode: EXIT_USAGE,
            hint: 'Pass the ID of the entity in PostHog.',
        })
        const stack = await resolveStack(ctx, options.stack, options.env)
        const checked = await checkStack(ctx, stack)
        if (!checked.ok) {
            throw new HogError(
                'stack_check_failed',
                'The definitions failed check.',
                'Run hog check and fix the problems before binding an entity.'
            )
        }
        if (!checked.description.resources.some((resource) => resource.kind === kind && resource.key === key)) {
            throw new HogError(
                'definition_missing',
                `The stack has no ${kind} definition with the key ${key}.`,
                `Check the kind and key with hog check --raw, or bring the entity into code with hog pull --adopt ${kind} ${shellWord(entityId)}${selectorFlags(stack)}.`,
                EXIT_USAGE
            )
        }
        const service = await stackService(ctx, stack)
        const binding = await service.bind({ kind, key, entity_id: entityId }).catch((error: unknown) => {
            if (error instanceof HogError && Object.hasOwn(hints, error.code)) {
                throw new HogError(
                    error.code,
                    error.message,
                    hints[error.code],
                    error.exitCode,
                    error.details,
                    error.serverDetail
                )
            }
            throw error
        })
        return {
            status: 'adopted' as const,
            kind,
            key,
            entityId,
            binding: binding.status,
            next: `hog diff${selectorFlags(stack)}`,
        }
    },
    human({ result, out }) {
        out.report({
            result: `Recorded a pending binding for ${escapeControls(`${result.kind} ${result.key}`)}`,
            effects: [escapeControls(`${result.kind} ${result.key} → entity ${result.entityId}`)],
            notes: [
                `The next push binds this entity to the definition and creates nothing for it. Run ${result.next} to review the push first.`,
            ],
        })
    },
    agent: ({ result, out }) => out.json(result),
})
