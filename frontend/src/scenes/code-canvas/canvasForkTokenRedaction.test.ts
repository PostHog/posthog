import { CaptureResult, CapturedNetworkRequest } from 'posthog-js'

import { canvasForkBeforeSend, canvasForkMaskNetworkRequest } from './canvasForkTokenRedaction'

describe('canvasForkTokenRedaction', () => {
    const send = (properties: Record<string, unknown>): Record<string, any> | undefined =>
        canvasForkBeforeSend({ event: '$pageview', properties } as unknown as CaptureResult)?.properties

    it.each([
        ['$current_url', 'https://us.posthog.com/desktop/canvas-fork/tok3n'],
        ['$pathname', '/desktop/canvas-fork/tok3n'],
        ['$referrer', 'https://us.posthog.com/desktop/canvas-fork/tok3n?utm_source=share'],
        ['$prev_pageview_pathname', '/desktop/canvas-fork/tok3n'],
        ['$current_url (legacy path)', 'https://us.posthog.com/code/canvas-fork/tok3n'],
        ['$pathname (legacy path)', '/code/canvas-fork/tok3n'],
    ])('strips the share token from %s', (property, value) => {
        expect(send({ [property]: value })?.[property]).toBe(value.replace('tok3n', '<redacted>'))
    })

    it('leaves properties without a share token alone', () => {
        expect(send({ $pathname: '/desktop/canvas/chan/1', $screen_height: 900 })).toEqual({
            $pathname: '/desktop/canvas/chan/1',
            $screen_height: 900,
        })
    })

    it('strips the share token from a recorded fork request', () => {
        const request = canvasForkMaskNetworkRequest({
            name: 'https://us.posthog.com/api/projects/2/canvases/fork/',
            requestBody: '{"share_token":"tok3n"}',
        } as CapturedNetworkRequest)

        expect(request.requestBody).toBe('{"share_token":"<redacted>"}')
    })
})
