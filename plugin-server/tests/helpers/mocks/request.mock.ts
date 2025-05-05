import { SecureResponse } from '../../../src/utils/request'

jest.mock('../../../src/utils/request', () => {
    return {
        secureRequest: jest.fn(() =>
            Promise.resolve({
                status: 200,
                body: JSON.stringify({ success: true }),
            } as SecureResponse)
        ),
    }
})

export const mockSecureRequest: jest.Mock<Promise<SecureResponse>> = require('../../../src/utils/request').secureRequest
