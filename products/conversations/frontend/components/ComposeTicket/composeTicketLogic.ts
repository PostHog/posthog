import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import type { EmailConfigStatus } from '../../scenes/settings/supportSettingsLogic'
import type { composeTicketLogicType } from './composeTicketLogicType'

export const composeTicketLogic = kea<composeTicketLogicType>([
    path(['products', 'conversations', 'frontend', 'components', 'ComposeTicket', 'composeTicketLogic']),
    actions({
        openComposeModal: (prefill?: { distinctId?: string; email?: string }) => ({ prefill }),
        closeComposeModal: true,
        setRecipientEmail: (email: string) => ({ email }),
        setRecipientDistinctId: (distinctId: string) => ({ distinctId }),
        setEmailSubject: (subject: string) => ({ subject }),
        setEmailConfigId: (configId: string) => ({ configId }),
        resetForm: true,
        submitCompose: (message: string, richContent: Record<string, unknown> | null) => ({ message, richContent }),
        submitComposeFinished: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                openComposeModal: () => true,
                closeComposeModal: () => false,
                resetForm: () => false,
            },
        ],
        recipientEmail: [
            '',
            {
                setRecipientEmail: (_, { email }) => email,
                openComposeModal: () => '',
                resetForm: () => '',
            },
        ],
        recipientDistinctId: [
            '',
            {
                setRecipientDistinctId: (_, { distinctId }) => distinctId,
                openComposeModal: () => '',
                resetForm: () => '',
            },
        ],
        emailSubject: [
            '',
            {
                setEmailSubject: (_, { subject }) => subject,
                openComposeModal: () => '',
                resetForm: () => '',
            },
        ],
        emailConfigId: [
            '',
            {
                setEmailConfigId: (_, { configId }) => configId,
                openComposeModal: () => '',
                resetForm: () => '',
            },
        ],
        composingLoading: [
            false,
            {
                submitCompose: () => true,
                submitComposeFinished: () => false,
                openComposeModal: () => false,
                resetForm: () => false,
            },
        ],
    }),
    loaders({
        emailConfigs: [
            [] as EmailConfigStatus[],
            {
                loadEmailConfigs: async (): Promise<EmailConfigStatus[]> => {
                    try {
                        // nosemgrep: prefer-codegen-api
                        const response = await api.get('api/conversations/v1/email/status')
                        return response.configs || []
                    } catch {
                        return []
                    }
                },
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        openComposeModal: ({ prefill }) => {
            if (prefill?.distinctId) {
                actions.setRecipientDistinctId(prefill.distinctId)
            }
            if (prefill?.email) {
                actions.setRecipientEmail(prefill.email)
            }
            actions.loadEmailConfigs()
        },
        submitCompose: async ({ message, richContent }) => {
            const { recipientEmail, recipientDistinctId, emailSubject, emailConfigId } = values

            if (!message.trim()) {
                lemonToast.error('Message is required.')
                actions.submitComposeFinished()
                return
            }

            if (!recipientEmail) {
                lemonToast.error('Recipient email is required.')
                actions.submitComposeFinished()
                return
            }

            if (!emailConfigId) {
                lemonToast.error('Please select a "From" email address.')
                actions.submitComposeFinished()
                return
            }

            try {
                const result = await api.conversationsTickets.compose({
                    message,
                    recipient_email: recipientEmail,
                    email_config_id: emailConfigId,
                    ...(recipientDistinctId ? { recipient_distinct_id: recipientDistinctId } : {}),
                    ...(emailSubject ? { email_subject: emailSubject } : {}),
                    ...(richContent ? { rich_content: richContent } : {}),
                })

                lemonToast.success('Ticket created successfully.')
                actions.resetForm()
                router.actions.push(urls.supportTicketDetail(result.ticket_number))
            } catch (error: unknown) {
                const detail =
                    error && typeof error === 'object' && 'detail' in error
                        ? (error as { detail: string }).detail
                        : 'Failed to create ticket.'
                lemonToast.error(detail)
                actions.submitComposeFinished()
            }
        },
    })),
])
