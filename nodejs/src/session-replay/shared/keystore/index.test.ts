import * as envUtils from '../../../utils/env-utils'
import { RetentionService } from '../retention/retention-service'
import { CleartextKeyStore } from './cleartext-keystore'
import { DynamoDBKeyStore } from './dynamodb-keystore'
import { getKeyStore } from './index'

jest.mock('../../../utils/env-utils', () => ({
    ...jest.requireActual('../../../utils/env-utils'),
    isCloud: jest.fn(),
}))

describe('getKeyStore', () => {
    let mockRetentionService: jest.Mocked<RetentionService>

    beforeEach(() => {
        mockRetentionService = {
            getSessionRetentionDays: jest.fn().mockResolvedValue(30),
        } as unknown as jest.Mocked<RetentionService>
    })

    it('should return DynamoDBKeyStore when running on cloud', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

        const keyStore = getKeyStore(mockRetentionService, 'us-east-1')

        expect(keyStore).toBeInstanceOf(DynamoDBKeyStore)
    })

    it('should return CleartextKeyStore when not running on cloud', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(false)

        const keyStore = getKeyStore(mockRetentionService, 'us-east-1')

        expect(keyStore).toBeInstanceOf(CleartextKeyStore)
    })

    it('should accept custom kmsEndpoint and dynamoDBEndpoint', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

        const keyStore = getKeyStore(mockRetentionService, 'us-east-1', {
            kmsEndpoint: 'http://localhost:4566',
            dynamoDBEndpoint: 'http://localhost:4566',
        })

        expect(keyStore).toBeInstanceOf(DynamoDBKeyStore)
    })
})
