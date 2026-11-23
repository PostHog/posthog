import { defineCommand } from '@/core/command'
import { stackOptions } from '@/stack/config'

import { secretName, secretNameArg, secretService } from './shared'

export default defineCommand({
    description: 'Remove a named secret from the stack',
    args: { name: secretNameArg },
    options: stackOptions,
    scopes: ['stack:write'],
    writes: true,
    examples: ['hog stack secret remove API_TOKEN'],
    async run({ ctx, args, options }) {
        const name = secretName(args.name)
        await (await secretService(ctx, options)).removeSecret(name)
        return { name }
    },
    human({ result, out }) {
        out.report({ result: `Removed secret ${result.name}` })
    },
    agent: ({ result, out }) => out.json(result),
})
