import nodemailer from 'nodemailer'

import { registerShutdownHandler } from '~/lifecycle'
import { isDevEnv, isTestEnv } from '~/utils/env-utils'
import { fetch } from '~/utils/request'

export const mailDevTransport =
    isDevEnv() || isTestEnv()
        ? nodemailer.createTransport({
              url: `http://${process.env.MAILDEV_HOST || '127.0.0.1'}:${process.env.MAILDEV_PORT || 1025}`,
              ignoreTLS: true,
              secure: false, // MailDev doesn't use TLS
              connectionTimeout: 1000, // ms
              greetingTimeout: 1000,
              socketTimeout: 1000,
          })
        : null

export const mailDevWebUrl = `http://${process.env.MAILDEV_HOST || '127.0.0.1'}:${process.env.MAILDEV_WEB_PORT || 1080}`

registerShutdownHandler(() => {
    return Promise.resolve(mailDevTransport?.close())
})

export class MailDevAPI {
    constructor() {}

    async getEmails(): Promise<any[]> {
        const response = await fetch(`${mailDevWebUrl}/email`)
        return response.json()
    }

    async clearEmails(): Promise<void> {
        await fetch(`${mailDevWebUrl}/email/all`, {
            method: 'DELETE',
        })
    }
}
