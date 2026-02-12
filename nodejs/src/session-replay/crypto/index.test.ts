import * as envUtils from '../../utils/env-utils'
import { KeyStore, SessionKey } from '../types'
import { CleartextRecordingDecryptor } from './cleartext-decryptor'
import { CleartextRecordingEncryptor } from './cleartext-encryptor'
import { getBlockDecryptor, getBlockEncryptor } from './index'
import { SodiumRecordingDecryptor } from './sodium-decryptor'
import { SodiumRecordingEncryptor } from './sodium-encryptor'

jest.mock('../../utils/env-utils', () => ({
    ...jest.requireActual('../../utils/env-utils'),
    isCloud: jest.fn(),
}))

describe('crypto factory functions', () => {
    const mockSessionKey: SessionKey = {
        plaintextKey: Buffer.from([
            1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
            30, 31, 32,
        ]),
        encryptedKey: Buffer.from([101, 102, 103, 104, 105]),
        sessionState: 'ciphertext',
    }

    let mockKeyStore: jest.Mocked<KeyStore>

    beforeEach(() => {
        mockKeyStore = {
            getKey: jest.fn().mockResolvedValue(mockSessionKey),
            generateKey: jest.fn(),
            deleteKey: jest.fn(),
        } as unknown as jest.Mocked<KeyStore>
    })

    describe('getBlockEncryptor', () => {
        it('should return SodiumRecordingEncryptor when running on cloud', () => {
            ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

            const encryptor = getBlockEncryptor(mockKeyStore)

            expect(encryptor).toBeInstanceOf(SodiumRecordingEncryptor)
        })

        it('should return CleartextRecordingEncryptor when not running on cloud', () => {
            ;(envUtils.isCloud as jest.Mock).mockReturnValue(false)

            const encryptor = getBlockEncryptor(mockKeyStore)

            expect(encryptor).toBeInstanceOf(CleartextRecordingEncryptor)
        })
    })

    describe('getBlockDecryptor', () => {
        it('should return SodiumRecordingDecryptor when running on cloud', () => {
            ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

            const decryptor = getBlockDecryptor(mockKeyStore)

            expect(decryptor).toBeInstanceOf(SodiumRecordingDecryptor)
        })

        it('should return CleartextRecordingDecryptor when not running on cloud', () => {
            ;(envUtils.isCloud as jest.Mock).mockReturnValue(false)

            const decryptor = getBlockDecryptor(mockKeyStore)

            expect(decryptor).toBeInstanceOf(CleartextRecordingDecryptor)
        })
    })
})
