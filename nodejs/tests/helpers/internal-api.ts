import supertest from 'supertest'
import express from 'ultimate-express'

import { INTERNAL_SERVICE_CALL_HEADER_NAME } from '~/common/api/middleware/internal-api-auth'
import { setupExpressApp } from '~/common/api/router'

export const TEST_INTERNAL_API_SECRET = 'test-internal-api-secret'

type AuthenticatedInternalApiRequest = {
    get(path: string): supertest.Test
    post(path: string): supertest.Test
}

export function setupInternalApiTestApp(): express.Application {
    return setupExpressApp({ internalApiSecret: TEST_INTERNAL_API_SECRET })
}

export function authenticatedInternalApiRequest(app: express.Application): AuthenticatedInternalApiRequest {
    return {
        get: (path: string) =>
            supertest(app).get(path).set(INTERNAL_SERVICE_CALL_HEADER_NAME, TEST_INTERNAL_API_SECRET),
        post: (path: string) =>
            supertest(app).post(path).set(INTERNAL_SERVICE_CALL_HEADER_NAME, TEST_INTERNAL_API_SECRET),
    }
}
