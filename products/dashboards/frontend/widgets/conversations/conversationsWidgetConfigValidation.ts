import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    conversationsRecentTicketsWidgetConfigSchema,
    conversationsRecentTicketsWidgetFormSchema,
    type ConversationsRecentTicketsWidgetConfig,
} from '../../generated/widget-configs.zod'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

export type ConversationsTicketStatus = NonNullable<ConversationsRecentTicketsWidgetConfig['status']>
export type ConversationsTicketPriority = NonNullable<ConversationsRecentTicketsWidgetConfig['priorities']>[number]
export type ConversationsTicketAssignee = NonNullable<ConversationsRecentTicketsWidgetConfig['assignees']>[number]
type ConversationsWidgetFormField = keyof z.infer<typeof conversationsRecentTicketsWidgetFormSchema>
export type ConversationsWidgetFieldErrors = Partial<Record<ConversationsWidgetFormField, string>>

export function parseConversationsWidgetConfig(
    config: Record<string, unknown>
): ConversationsRecentTicketsWidgetConfig {
    return parseWidgetConfig(conversationsRecentTicketsWidgetConfigSchema, config)
}

export function patchConversationsWidgetConfig(
    config: Record<string, unknown>,
    patch: Partial<ConversationsRecentTicketsWidgetConfig>
): ConversationsRecentTicketsWidgetConfig {
    return conversationsRecentTicketsWidgetConfigSchema.parse({ ...parseConversationsWidgetConfig(config), ...patch })
}

export function patchConversationsWidgetFilterFields(
    config: Record<string, unknown>,
    patch: {
        status?: ConversationsTicketStatus
        priorities?: ConversationsTicketPriority[]
        assignees?: ConversationsTicketAssignee[]
        savedViewId?: string | null
    }
): ConversationsRecentTicketsWidgetConfig {
    const base = parseConversationsWidgetConfig(config)
    return conversationsRecentTicketsWidgetConfigSchema.parse({
        ...base,
        status: patch.status ?? base.status,
        priorities: patch.priorities ?? base.priorities,
        assignees: patch.assignees ?? base.assignees,
        savedViewId: 'savedViewId' in patch ? patch.savedViewId : base.savedViewId,
    })
}

export function parseConversationsWidgetConfigApiError(
    error: unknown,
    config: Record<string, unknown>
): ConversationsWidgetFieldErrors | null {
    if (!(error instanceof ApiError)) {
        return null
    }
    const parsed = conversationsRecentTicketsWidgetConfigSchema.safeParse(config)
    return parsed.success ? null : fieldErrorsFromZodError(parsed.error)
}
