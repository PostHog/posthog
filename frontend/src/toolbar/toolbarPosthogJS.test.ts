import '~/toolbar/toolbarPosthogJS'

import posthog, { CaptureResult, PostHogConfig } from 'posthog-js'

// Captured at module load, before clearMocks empties the call record.
const initConfig = (posthog.init as jest.Mock).mock.calls[0][1] as Partial<PostHogConfig>

const beforeSend = (
    event: string,
    properties: Record<string, unknown> = {},
    personProperties: Pick<CaptureResult, '$set' | '$set_once'> = {}
): CaptureResult | null => {
    const guard = initConfig.before_send as (event: CaptureResult) => CaptureResult | null
    return guard({ event, properties, ...personProperties } as CaptureResult)
}

describe('toolbar posthog instance', () => {
    // The toolbar runs inside every customer's site. Each of these options is enabled by the
    // internal project's remote config when left unset, which is how host page web vitals, dead
    // clicks and exceptions reached our project.
    it.each([
        ['autocapture'],
        ['capture_dead_clicks'],
        ['capture_exceptions'],
        ['capture_heatmaps'],
        ['capture_pageleave'],
        ['capture_performance'],
        ['capture_pageview'],
        ['save_campaign_params'],
        ['save_referrer'],
    ])('turns %s off at init', (option) => {
        expect(initConfig[option as keyof PostHogConfig]).toBe(false)
    })

    // The guard holds even if an init option above is dropped or a remote config wins.
    it.each([
        ['$autocapture'],
        ['$copy_autocapture'],
        ['$dead_click'],
        ['$pageleave'],
        ['$pageview'],
        ['$rageclick'],
        ['$web_vitals'],
        ['$$heatmap'],
    ])('drops %s, which describes the host page', (event) => {
        expect(beforeSend(event)).toBeNull()
    })

    it('drops an exception the toolbar did not report about itself', () => {
        expect(beforeSend('$exception', { $exception_message: 'host page code failed' })).toBeNull()
    })

    it.each([
        ['$exception', { toolbar_context: 'kea_loader' }],
        ['toolbar loaded', {}],
    ])('keeps %s, which the toolbar reports about itself', (event, properties) => {
        expect(beforeSend(event as string, properties as Record<string, unknown>)).not.toBeNull()
    })

    // posthog-js reads these off the host page URL and referrer and adds them before the guard
    // runs, so an event the guard keeps still describes the customer's page unless they are removed.
    it.each([
        ['$current_url'],
        ['$host'],
        ['$pathname'],
        ['$referrer'],
        ['$referring_domain'],
        ['$search_engine'],
        ['ph_keyword'],
        ['utm_source'],
        ['gclid'],
        ['$initial_current_url'],
        ['$initial_referrer'],
        ['$initial_utm_campaign'],
        ['$session_entry_url'],
        ['$session_entry_referring_domain'],
    ])('strips %s from an event it keeps', (property) => {
        const result = beforeSend('toolbar loaded', { [property]: 'host page value', is_authenticated: true })

        expect(result?.properties).toEqual({ is_authenticated: true })
    })

    it('strips host page properties from the person properties', () => {
        const result = beforeSend(
            'toolbar loaded',
            {},
            {
                $set: { email: 'engineer@example.com', $current_url: 'https://customer.example.com/cart?utm_source=x' },
                $set_once: { $initial_referrer: 'https://search.example.com/', $initial_host: 'customer.example.com' },
            }
        )

        expect(result?.$set).toEqual({ email: 'engineer@example.com' })
        expect(result?.$set_once).toEqual({})
    })

    // `pathname` is the toolbar's own API path, and `$initialization_time` is not an `$initial_`
    // property. Neither describes the host page.
    it('keeps the properties the toolbar reports about itself', () => {
        const properties = {
            pathname: '/api/projects/@current/actions/',
            status: 200,
            $lib: 'web',
            $initialization_time: '2026-01-01T00:00:00.000Z',
        }

        expect(beforeSend('toolbar api request', { ...properties })?.properties).toEqual(properties)
    })
})
