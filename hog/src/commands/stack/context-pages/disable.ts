import { defineCommand } from '@/core/command'
import { stackOptions } from '@/stack/config'

import { setContextPages } from './shared'

export default defineCommand({
    description: 'Stop this stack from managing context pages. Only an organization admin can',
    options: stackOptions,
    scopes: ['stack:write'],
    writes: true,
    notes: 'The pages stay in PostHog. A later diff of a stack that still defines context pages fails until they are allowed again.',
    examples: ['hog stack context-pages disable --stack web'],

    async run({ ctx, options }) {
        return { status: 'disabled' as const, ...(await setContextPages(ctx, options, false)) }
    },
    human({ result, out }) {
        out.report({ result: `Stack ${result.stack} no longer manages context pages` })
    },
    agent: ({ result, out }) => out.json(result),
})
