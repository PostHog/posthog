import { defineCommand } from '@/core/command'
import { stackOptions } from '@/stack/config'

import { secretService } from './shared'

export default defineCommand({
    description: 'List the names of the secrets in a stack and when each was last set',
    options: stackOptions,
    scopes: ['stack:read'],
    examples: ['hog stack secret list'],
    async run({ ctx, options }) {
        const secrets = await (await secretService(ctx, options)).listSecrets()
        return { secrets }
    },
    human({ result, out }) {
        if (!result.secrets.length) {
            out.line('This stack has no secrets.')
            return
        }
        out.table(
            ['Name', 'Last set'],
            result.secrets.map(({ name, updated_at }) => [name, updated_at])
        )
    },
    agent: ({ result, out }) => out.json(result),
})
