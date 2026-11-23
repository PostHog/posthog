import { defineCommand } from '@/core/command'
import { EXIT_NEEDS_PERSON, HogError } from '@/core/errors'
import { resolveStack, stackOptions } from '@/stack/config'
import { selectorFlags } from '@/stack/diff'

import { setContextPages, SHARED_PAGES } from './shared'

export default defineCommand({
    description: 'Let this stack manage context pages. Only an organization admin can',
    options: {
        ...stackOptions,
        yes: {
            type: 'boolean',
            short: 'y',
            description: 'Confirm without a prompt, after a person who is an organization admin agreed',
        },
    },
    scopes: ['stack:write'],
    writes: true,
    notes: `${SHARED_PAGES} Turn it off again with hog stack context-pages disable.`,
    examples: ['hog stack context-pages enable --stack web'],

    async run({ ctx, options }) {
        if (!options.yes) {
            const stack = await resolveStack(ctx, options.stack, options.env)
            if (!ctx.prompts) {
                throw new HogError(
                    'confirmation_required',
                    'Letting a stack manage context pages affects every project in the organization.',
                    `Ask an organization admin to agree, then run hog stack context-pages enable${selectorFlags(stack)} --yes, or let them run it at a terminal.`,
                    EXIT_NEEDS_PERSON
                )
            }
            ctx.prompts.note(SHARED_PAGES, 'Context pages')
            if (
                !(await ctx.prompts.confirm(`Let stack ${stack.name ?? stack.dir} manage context pages?`, {
                    initialValue: false,
                }))
            ) {
                return { status: 'cancelled' as const }
            }
        }
        return { status: 'enabled' as const, ...(await setContextPages(ctx, options, true)) }
    },
    human({ result, out }) {
        if (result.status === 'cancelled') {
            out.report({ result: 'Context pages stay off for this stack', status: 'unchanged' })
            return
        }
        out.report({
            result: `Stack ${result.stack} may now manage context pages`,
            notes: ['Run hog diff to review the pages before pushing.'],
        })
    },
    agent: ({ result, out }) => out.json(result),
})
