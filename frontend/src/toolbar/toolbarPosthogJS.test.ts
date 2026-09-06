import '~/toolbar/toolbarPosthogJS'

import posthog, { CaptureResult, PostHogConfig } from 'posthog-js'

// Captured at module load, before clearMocks empties the call record.
const initConfig = (posthog.init as jest.Mock).mock.calls[0][1] as Partial<PostHogConfig>

const beforeSend = (event: string, properties: Record<string, unknown> = {}): CaptureResult | null => {
    const guard = initConfig.before_send as (event: CaptureResult) => CaptureResult | null
    return guard({ event, properties } as CaptureResult)
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
})
