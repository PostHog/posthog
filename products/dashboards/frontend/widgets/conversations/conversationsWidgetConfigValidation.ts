import { z } from 'zod'

import { ApiError } from 'lib/api-error'

import {
    conversationsRecentTicketsWidgetConfigSchema,
    conversationsRecentTicketsWidgetFormSchema,
    type ConversationsRecentTicketsWidgetConfig,
} from '../../generated/widget-configs.zod'
import { fieldErrorsFromZodError, parseWidgetConfig } from '../widgetConfigValidation'

export type ConversationsTicketStatus = NonNullable<ConversationsRecentTicketsWidgetConfig['status']>
type ConversationsWidgetFormField = keyof z.infer<typeof conversationsRecentTicketsWidgetFormSchema>
export type ConversationsWidgetFieldErrors = Partial<Record<ConversationsWidgetFormField, string>>

export const CONVERSATIONS_TICKET_STATUS_OPTIONS: { value: ConversationsTicketStatus; label: string }[] = [
    { value: 'all', label: 'All statuses' },
    { value: 'new', label: 'New' },
    { value: 'open', label: 'Open' },
    { value: 'pending', label: 'Pending' },
    { value: 'on_hold', label: 'On hold' },
    { value: 'resolved', label: 'Resolved' },
]

export function parseConversationsWidgetConfig(
    config: Record<string, unknown>
): ConversationsRecentTicketsWidgetConfig {
    return parseWidgetConfig(conversationsRecentTicketsWidgetConfigSchema, config)
}

export function patchConversationsWidgetStatus(
    config: Record<string, unknown>,
    status: ConversationsTicketStatus
): ConversationsRecentTicketsWidgetConfig {
    return conversationsRecentTicketsWidgetConfigSchema.parse({ ...parseConversationsWidgetConfig(config), status })
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
