import purify from 'dompurify'

const sanitizeConfig = { ADD_ATTR: ['target'] }

export function sanitizeHTML(html: string): string {
    return purify.sanitize(html, sanitizeConfig)
}
