import DomPurify from 'dompurify'

const sanitizeConfig = { ADD_ATTR: ['target'] }

export function sanitizeHTML(html: string): string {
    return DomPurify.sanitize(html, sanitizeConfig)
}
