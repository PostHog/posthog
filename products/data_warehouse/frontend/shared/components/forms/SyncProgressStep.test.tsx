import { getPreviewQueryUrl, getSourceAccessMethod } from './SyncProgressStep'

describe('SyncProgressStep', () => {
    it('prefers the wizard access method before the source has loaded', () => {
        expect(getSourceAccessMethod('direct', undefined)).toEqual('direct')
    })

    it('uses the loaded source access method when available', () => {
        expect(getSourceAccessMethod('warehouse', 'direct')).toEqual('direct')
    })

    it('includes the direct connection id in SQL editor preview URLs', () => {
        const previewUrl = new URL(getPreviewQueryUrl('orders', 'direct', 'source-123'), 'https://app.posthog.com')

        expect(new URLSearchParams(previewUrl.hash.slice(1)).get('c')).toEqual('source-123')
    })

    it('stores the preview query in the URL hash', () => {
        const previewUrl = new URL(getPreviewQueryUrl('orders', 'direct', 'source-123'), 'https://app.posthog.com')

        expect(previewUrl.hash).toContain('q=SELECT+*+FROM+orders+LIMIT+100')
    })

    it('quotes dotted table names as a single HogQL identifier', () => {
        const previewUrl = new URL(getPreviewQueryUrl('demo.orders', 'direct', 'source-123'), 'https://app.posthog.com')

        expect(new URLSearchParams(previewUrl.hash.slice(1)).get('q')).toEqual('SELECT * FROM demo.orders LIMIT 100')
    })

    it('does not include a connection id for warehouse preview URLs', () => {
        expect(getPreviewQueryUrl('orders', 'warehouse', 'source-123')).not.toContain('#c=')
    })
})
