import { z } from 'zod'

import { HogFunctionQueueParametersFetchRequest } from '../types'

const EmailInputSchema = z.object({
    from: z.string().email().min(1),
    from_name: z.string().optional(),
    to: z.string().email().min(1),
    to_name: z.string().optional(),
    subject: z.string(),
    html: z.string(),
})

const MailjetCredentialsSchema = z.object({
    api_key: z.string(),
    secret_key: z.string(),
})

const ResendCredentialsSchema = z.object({
    secret_key: z.string(),
})

type EmailInput = z.infer<typeof EmailInputSchema>
type MailjetCredentials = z.infer<typeof MailjetCredentialsSchema>
type ResendCredentials = z.infer<typeof ResendCredentialsSchema>
export const createEmailRequest = (
    email: EmailInput,
    credentials: MailjetCredentials | ResendCredentials,
    vendor: 'mailjet' | 'resend'
): Omit<HogFunctionQueueParametersFetchRequest, 'return_queue'> => {
    const { from, from_name, to, to_name, subject, html } = EmailInputSchema.parse(email)

    switch (vendor) {
        case 'mailjet': {
            const { api_key, secret_key } = MailjetCredentialsSchema.parse(credentials)
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
        case 'resend': {
            const { secret_key } = ResendCredentialsSchema.parse(credentials)
            return {
                url: 'https://api.resend.com/emails',
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${secret_key}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    from: from_name ? `${from_name} <${from}>` : from,
                    to: to_name ? `${to_name} <${to}>` : to,
                    subject,
                    html,
                }),
            }
        }
    }
}
