import { z } from 'zod'

import { HogFunctionQueueParametersFetchRequest } from '../types'

const MailjetEmailInputSchema = z.object({
    from: z.string().email().min(1),
    from_name: z.string().optional(),
    to: z.string().email().min(1),
    to_name: z.string().optional(),
    subject: z.string(),
    html: z.string(),
})
type MailjetEmailInput = z.infer<typeof MailjetEmailInputSchema>

const MailjetCredentialsSchema = z.object({
    api_key: z.string(),
    secret_key: z.string(),
})
type MailjetCredentials = z.infer<typeof MailjetCredentialsSchema>

const EmailIntegrationConfigSchema = z.object({
    domain: z.string(),
    mailjet_verified: z.boolean(),
})
type EmailIntegrationConfig = z.infer<typeof EmailIntegrationConfigSchema>

export const createMailjetRequest = (
    email: MailjetEmailInput,
    config: EmailIntegrationConfig,
    credentials: MailjetCredentials
): Omit<HogFunctionQueueParametersFetchRequest, 'return_queue'> => {
    const { from, from_name, to, to_name, subject, html } = MailjetEmailInputSchema.parse(email)
    const { domain, mailjet_verified } = EmailIntegrationConfigSchema.parse(config)
    const { api_key, secret_key } = credentials

    if (from.split('@')[1] !== domain) {
        throw new Error('From address must use the same verified domain configured for this email')
    }

    if (!mailjet_verified) {
        throw new Error(`Domain ${domain} has not yet been verified`)
    }

    return {
        url: 'https://api.mailjet.com/v3.1/send',
        method: 'POST',
        headers: {
            Authorization: `Basic ${Buffer.from(`${api_key}:${secret_key}`).toString('base64')}`,
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            Messages: [
                {
                    From: {
                        Email: from,
                        Name: from_name || '',
                    },
                    To: [
                        {
                            Email: to,
                            Name: to_name || '',
                        },
                    ],
                    Subject: subject,
                    HTMLPart: html,
                },
            ],
        }),
    }
}
