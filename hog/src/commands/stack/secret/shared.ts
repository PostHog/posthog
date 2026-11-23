import type { Context } from '@/core/context'
import { EXIT_USAGE } from '@/core/errors'
import { resolveStack } from '@/stack/config'
import { parseSecretName, stackService, type StackService } from '@/stack/service'

export const secretNameArg = {
    description: 'The name used by secret() in the stack definitions',
} as const

export function secretName(value: string): string {
    return parseSecretName(value, {
        code: 'invalid_secret_name',
        hint: 'Use up to 100 letters, digits and underscores. Start with a letter or underscore.',
        exitCode: EXIT_USAGE,
    })
}

export async function secretService(ctx: Context, options: { stack?: string; env?: string }): Promise<StackService> {
    const stack = await resolveStack(ctx, options.stack, options.env)
    return stackService(ctx, stack)
}
