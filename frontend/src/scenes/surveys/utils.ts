import { sanitize } from 'dompurify'

const sanitizeConfig = { ADD_ATTR: ['target'] }

export function sanitizeHTML(html: string): string {
    return sanitize(html, sanitizeConfig)
}
