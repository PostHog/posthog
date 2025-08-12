import nodemailer from 'nodemailer'

import { isDevEnv } from '~/utils/env-utils'

export const mailDevTransport = isDevEnv()
    ? nodemailer.createTransport({
          url: `http://${process.env.MAILDEV_HOST || 'localhost'}:${process.env.MAILDEV_PORT || 1025}`,
          secure: false, // MailDev doesn't use TLS
      })
    : null

export const mailDevWebUrl = `http://${process.env.MAILDEV_HOST || 'localhost'}:${process.env.MAILDEV_WEB_PORT || 1080}`
