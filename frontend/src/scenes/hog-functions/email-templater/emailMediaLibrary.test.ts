import type { Editor } from 'react-email-editor'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { registerEmailMediaLibrary } from './emailMediaLibrary'

jest.mock('posthog-js')

type Handler = (...args: any[]) => Promise<void>

function registerOnFakeEditor(): Record<string, Handler> {
    const handlers: Record<string, Handler> = {}
    const editor = {
        registerProvider: (type: string, handler: Handler) => (handlers[`provider:${type}`] = handler),
        registerCallback: (type: string, handler: Handler) => (handlers[type] = handler),
    } as unknown as Editor
    registerEmailMediaLibrary(editor, '1')
    return handlers
}

const MEDIA = {
    id: 'media-1',
    name: 'logo.png',
    purpose: 'email',
    content_type: 'image/png',
    size_bytes: 1024,
    width: null,
    height: null,
    url: 'http://localhost/uploaded_media/media-1',
    created_at: '2026-10-01T00:00:00Z',
}

describe('registerEmailMediaLibrary', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('lists a page of the email library in the shape the Uploads tab expects', async () => {
        const requestedParams: URLSearchParams[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/uploaded_media/': ({ request }) => {
                    requestedParams.push(new URL(request.url).searchParams)
                    return [200, { count: 41, next: 'http://localhost/next', previous: null, results: [MEDIA] }]
                },
            },
        })
        const done = jest.fn()

        await registerOnFakeEditor()['provider:userUploads']({ page: 3, searchText: ' logo ' }, done)

        expect(Object.fromEntries(requestedParams[0])).toEqual({
            purpose: 'email',
            limit: '20',
            offset: '40',
            search: 'logo',
        })
        expect(done).toHaveBeenCalledWith(
            [
                {
                    id: 'media-1',
                    location: 'http://localhost/uploaded_media/media-1',
                    width: 0,
                    height: 0,
                    contentType: 'image/png',
                    size: 1024,
                    source: 'user',
                },
            ],
            { hasMore: true, page: 3, perPage: 20, total: 41 }
        )
    })

    it.each([
        [
            'shows the reason the backend rejected the file',
            [400, { detail: 'Uploaded media must be less than 4MB' }],
            'Uploaded media must be less than 4MB',
        ],
        ['falls back to a generic message without one', [500, {}], "Couldn't upload this image. Try again."],
    ])('upload failure %s', async (_name, response, expectedError) => {
        useMocks({ post: { '/api/projects/:team_id/uploaded_media/': () => response } })
        const done = jest.fn()

        await registerOnFakeEditor()['image']({ attachments: [new File(['x'], 'big.png')] }, done)

        expect(done).toHaveBeenLastCalledWith({ error: expectedError })
    })

    it.each([
        ['removed now', 204, true],
        ['already removed', 404, true],
        ['failed to remove', 500, false],
    ])('reports removal as finished only when the image is out of the library: %s', async (_name, status, finished) => {
        useMocks({ delete: { '/api/projects/:team_id/uploaded_media/:id/': () => [status] } })
        const done = jest.fn()

        await registerOnFakeEditor()['image:removed']({ id: 'media-1' }, done)

        expect(done).toHaveBeenCalledTimes(finished ? 1 : 0)
    })
})
