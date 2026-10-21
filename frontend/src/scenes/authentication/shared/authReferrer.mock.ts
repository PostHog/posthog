export const WEBSITE_REFERRER = 'https://posthog.com/pricing'

export function setDocumentReferrer(referrer: string): void {
    Object.defineProperty(document, 'referrer', { value: referrer, configurable: true })
}
