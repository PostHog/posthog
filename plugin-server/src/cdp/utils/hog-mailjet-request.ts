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

const MailjetCredentialsSchema = z.object({
    api_key: z.string(),
    secret_key: z.string(),
})

type MailjetEmailInput = z.infer<typeof MailjetEmailInputSchema>
type MailjetCredentials = z.infer<typeof MailjetCredentialsSchema>

export const createMailjetRequest = (
    email: MailjetEmailInput,
    credentials: MailjetCredentials
): Omit<HogFunctionQueueParametersFetchRequest, 'return_queue'> => {
    const { from, from_name, to, to_name, subject, html } = MailjetEmailInputSchema.parse(email)
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
