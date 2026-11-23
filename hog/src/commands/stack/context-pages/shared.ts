import type { Context } from '@/core/context'
import { resolveStack } from '@/stack/config'
import { stackService } from '@/stack/service'

export const SHARED_PAGES =
    'Context pages belong to the organization, so every project in it shares them. While a stack may manage them, its pushes run with organization-wide read and write scopes for context pages.'

interface ContextPagesSetting {
    stack: string
    contextPagesEnabled: boolean
}

export async function setContextPages(
    ctx: Context,
    options: { stack?: string; env?: string },
    enabled: boolean
): Promise<ContextPagesSetting> {
    const stack = await resolveStack(ctx, options.stack, options.env)
    const service = await stackService(ctx, stack)
    const settings = await service.setContextPages(enabled)
    return { stack: settings.name, contextPagesEnabled: settings.context_pages_enabled }
}
