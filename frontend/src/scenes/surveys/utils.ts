import DOMPurify from 'dompurify'

const sanitizeConfig = { ADD_ATTR: ['target'] }

export function sanitizeHTML(html: string): string {
    return DOMPurify.sanitize(html, sanitizeConfig)
}
