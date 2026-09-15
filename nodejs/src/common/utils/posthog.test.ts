type CapturedException = { distinctId?: string; properties?: Record<string, any> }

const capturedExceptions: CapturedException[] = []

jest.mock('posthog-node', () => ({
    PostHog: jest.fn().mockImplementation(() => ({
        captureException: (_exception: unknown, distinctId?: string, properties?: Record<string, any>) => {
            capturedExceptions.push({ distinctId, properties })
        },
        disable: () => Promise.resolve(),
        register: () => {},
    })),
}))

describe('captureException', () => {
    const originalEnv = { ...process.env }
    let captureException: (exception: any, hint?: any) => void

    beforeAll(() => {
        process.env.POSTHOG_API_KEY = 'phc_test'
        process.env.OTEL_SERVICE_NAME = 'plugin-server'
        process.env.OTEL_SERVICE_ENVIRONMENT = 'test'
        jest.isolateModules(() => {
            captureException = require('~/common/utils/posthog').captureException
        })
    })

    beforeEach(() => {
        capturedExceptions.length = 0
    })

    afterAll(() => {
        process.env = originalEnv
    })

    it('sends every exception under the same distinct id, without person processing', () => {
        captureException(new Error('first failure'))
        captureException(new Error('second failure'), { tags: { team: 'ingestion' } })

        expect(capturedExceptions).toEqual([
            { distinctId: 'plugin-server:test', properties: { $process_person_profile: false } },
            {
                distinctId: 'plugin-server:test',
                properties: { team: 'ingestion', $process_person_profile: false },
            },
        ])
    })
})
