import * as envUtils from '~/common/utils/env-utils'

import { CleartextKeyStore } from './cleartext-keystore'
import { DynamoDBKeyStore } from './dynamodb-keystore'
import { getKeyStore } from './index'

jest.mock('~/common/utils/env-utils', () => ({
    ...jest.requireActual('~/common/utils/env-utils'),
    isCloud: jest.fn(),
}))

describe('getKeyStore', () => {
    it('should return DynamoDBKeyStore when running on cloud', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

        const keyStore = getKeyStore('us-east-1')

        expect(keyStore).toBeInstanceOf(DynamoDBKeyStore)
    })

    it('should return CleartextKeyStore when not running on cloud', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(false)

        const keyStore = getKeyStore('us-east-1')

        expect(keyStore).toBeInstanceOf(CleartextKeyStore)
    })

    it('should accept custom kmsEndpoint and dynamoDBEndpoint', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

        const keyStore = getKeyStore('us-east-1', {
            kmsEndpoint: 'http://localhost:4566',
            dynamoDBEndpoint: 'http://localhost:4566',
        })

        expect(keyStore).toBeInstanceOf(DynamoDBKeyStore)
    })
})
