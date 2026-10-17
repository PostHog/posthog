import { Code, ConnectError } from '@connectrpc/connect'

import type * as PosthogModule from './posthog'

const mockCaptureException = jest.fn()

jest.mock('posthog-node', () => ({
    PostHog: jest.fn().mockImplementation(() => ({
        captureException: (...args: unknown[]) => mockCaptureException(...args),
        disable: jest.fn(),
    })),
}))
jest.mock('../config/config', () => ({
    defaultConfig: { POSTHOG_API_KEY: 'test-key', POSTHOG_HOST_URL: 'http://localhost' },
}))

describe('captureException', () => {
    // jest.setup.ts loads this module before the mocks above apply, so load a fresh copy.
    let captureException: typeof PosthogModule.captureException
    jest.isolateModules(() => {
        captureException = (jest.requireActual('./posthog') as typeof PosthogModule).captureException
    })

    it.each([
        [
            'retriable ConnectError',
            Object.assign(new ConnectError('Server at capacity', Code.Unavailable), { isRetriable: true }),
            false,
        ],
        ['untagged ConnectError', new ConnectError('permission denied', Code.PermissionDenied), true],
        ['plain error tagged retriable', Object.assign(new Error('boom'), { isRetriable: true }), true],
    ])('%s', (_name, error, captured) => {
        captureException(error)

        expect(mockCaptureException).toHaveBeenCalledTimes(captured ? 1 : 0)
    })
})
