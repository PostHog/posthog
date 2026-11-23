import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { stackOptions } from '@/stack/config'
import { parseSecretValue } from '@/stack/service'

import { secretName, secretNameArg, secretService } from './shared'

const LINE_BREAK_NOTE =
    "The stored value ends with a line break. To store it without one, run the command again and pipe the value with printf '%s' instead of echo."

export default defineCommand({
    description: 'Set or replace a secret from stdin or a hidden prompt',
    args: {
        name: secretNameArg,
        input: {
            optional: true,
            stdin: true,
            stdinOnly: true,
            description:
                "Pass - to read the value from stdin. At a terminal hog asks for it privately. hog stores the value exactly as given, including a final line break, so pipe it with printf '%s' rather than echo",
        },
    },
    options: stackOptions,
    scopes: ['stack:write'],
    writes: true,
    examples: ['hog stack secret set API_TOKEN', 'hog stack secret set API_TOKEN - < token.txt'],
    async run({ ctx, args, options }) {
        const name = secretName(args.name)
        const input = args.input ?? (await ctx.prompts?.password(`Value for ${name}`))
        if (input === undefined) {
            throw new HogError(
                'secret_input_required',
                'This command needs a secret value.',
                'Pipe the value to hog stack secret set NAME -.',
                EXIT_USAGE
            )
        }
        const value = parseSecretValue(input)
        await (await secretService(ctx, options)).setSecret(name, value)
        return /\r?\n$/.test(value) ? { name, endsWithLineBreak: true as const, note: LINE_BREAK_NOTE } : { name }
    },
    human({ result, out }) {
        out.report({
            result: `Set secret ${result.name}`,
            warnings: result.note ? [result.note] : [],
        })
    },
    agent: ({ result, out }) => out.json(result),
})
