import sodium from 'libsodium-wrappers'

import * as envUtils from '../utils/env-utils'
import { PassthroughRecordingEncryptor, RecordingEncryptor, getBlockEncryptor } from './recording-encryptor'
import { BaseKeyStore, BaseRecordingEncryptor, SessionKey, SessionKeyDeletedError } from './types'

jest.mock('../utils/env-utils', () => ({
    ...jest.requireActual('../utils/env-utils'),
    isCloud: jest.fn(),
}))

describe('recording-encryptor', () => {
    beforeAll(async () => {
        await sodium.ready
    })

    const mockPlaintextKey = Buffer.from([
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30,
        31, 32,
    ])
    const mockNonce = Buffer.from([
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
    ])
    const mockEncryptedKey = Buffer.from([101, 102, 103, 104, 105])

    const mockSessionKey: SessionKey = {
        plaintextKey: mockPlaintextKey,
        encryptedKey: mockEncryptedKey,
        nonce: mockNonce,
        sessionState: 'ciphertext',
    }

    describe('PassthroughRecordingEncryptor', () => {
        let mockKeyStore: jest.Mocked<BaseKeyStore>

        beforeEach(() => {
            mockKeyStore = {
                start: jest.fn(),
                getKey: jest.fn(),
                generateKey: jest.fn(),
                deleteKey: jest.fn(),
                stop: jest.fn(),
            } as unknown as jest.Mocked<BaseKeyStore>
        })

        it('should complete start without error', async () => {
            const encryptor = new PassthroughRecordingEncryptor(mockKeyStore)
            await expect(encryptor.start()).resolves.toBeUndefined()
        })

        it('should return clearText unchanged', async () => {
            const encryptor = new PassthroughRecordingEncryptor(mockKeyStore)
            const clearText = Buffer.from('hello world')

            const result = await encryptor.encryptBlock('session-123', 1, clearText)

            expect(result).toEqual(clearText)
        })

        it('should extend BaseRecordingEncryptor', () => {
            const encryptor = new PassthroughRecordingEncryptor(mockKeyStore)
            expect(encryptor).toBeInstanceOf(BaseRecordingEncryptor)
        })
    })

    describe('RecordingEncryptor', () => {
        let mockKeyStore: jest.Mocked<BaseKeyStore>

        beforeEach(() => {
            mockKeyStore = {
                getKey: jest.fn().mockResolvedValue(mockSessionKey),
                generateKey: jest.fn(),
                deleteKey: jest.fn(),
            } as unknown as jest.Mocked<BaseKeyStore>
        })

        it('should create instance via constructor', () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)

            expect(encryptor).toBeInstanceOf(RecordingEncryptor)
            expect(encryptor).toBeInstanceOf(BaseRecordingEncryptor)
        })

        it('should initialize sodium on start', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            await expect(encryptor.start()).resolves.toBeUndefined()
        })

        it('should encrypt clearText using keyStore key', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const clearText = Buffer.from('hello world')

            const result = await encryptor.encryptBlock('session-123', 1, clearText)

            expect(mockKeyStore.getKey).toHaveBeenCalledWith('session-123', 1)
            expect(result).toBeInstanceOf(Buffer)
            expect(result.length).toBeGreaterThan(0)
            expect(result).not.toEqual(clearText)
        })

        it('should throw error if getKey fails', async () => {
            mockKeyStore.getKey.mockRejectedValue(new Error('Key not found'))
            const encryptor = new RecordingEncryptor(mockKeyStore)

            await expect(encryptor.encryptBlock('session-123', 1, Buffer.from('test'))).rejects.toThrow('Key not found')
        })

        it('should handle empty buffer', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const clearText = Buffer.from('')

            const result = await encryptor.encryptBlock('session-123', 1, clearText)

            expect(result).toBeInstanceOf(Buffer)
            expect(result.length).toBeGreaterThan(0)
        })

        it('should handle large buffer', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const clearText = Buffer.alloc(1024 * 1024, 'x')

            const result = await encryptor.encryptBlock('session-123', 1, clearText)

            expect(result).toBeInstanceOf(Buffer)
            expect(result.length).toBeGreaterThan(clearText.length)
        })

        it('should produce consistent output for same input', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const clearText = Buffer.from('hello world')

            const result1 = await encryptor.encryptBlock('session-123', 1, clearText)
            const result2 = await encryptor.encryptBlock('session-123', 1, clearText)

            expect(result1).toEqual(result2)
        })

        it('should handle binary data', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const binaryData = Buffer.from([0x00, 0x01, 0x02, 0xff, 0xfe, 0xfd])

            const result = await encryptor.encryptBlock('session-123', 1, binaryData)

            expect(result).toBeInstanceOf(Buffer)
            expect(result).not.toEqual(binaryData)
        })

        it('should throw SessionKeyDeletedError when session state is deleted', async () => {
            const deletedAt = 1700000000
            const deletedSessionKey: SessionKey = {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                nonce: Buffer.alloc(0),
                sessionState: 'deleted',
                deletedAt,
            }
            mockKeyStore.getKey.mockResolvedValue(deletedSessionKey)

            const encryptor = new RecordingEncryptor(mockKeyStore)

            await expect(encryptor.encryptBlock('session-123', 1, Buffer.from('test'))).rejects.toThrow(
                SessionKeyDeletedError
            )
            await expect(encryptor.encryptBlock('session-123', 1, Buffer.from('test'))).rejects.toThrow(
                'Session key has been deleted for session session-123 team 1'
            )

            try {
                await encryptor.encryptBlock('session-123', 1, Buffer.from('test'))
            } catch (error) {
                expect((error as SessionKeyDeletedError).deletedAt).toBe(deletedAt)
            }
        })

        it('should return data unchanged when session state is cleartext', async () => {
            const cleartextSessionKey: SessionKey = {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                nonce: Buffer.alloc(0),
                sessionState: 'cleartext',
            }
            mockKeyStore.getKey.mockResolvedValue(cleartextSessionKey)

            const encryptor = new RecordingEncryptor(mockKeyStore)
            const clearText = Buffer.from('hello world')

            const result = await encryptor.encryptBlock('session-123', 1, clearText)

            expect(result).toEqual(clearText)
        })
    })

    describe('getBlockEncryptor', () => {
        let mockKeyStore: jest.Mocked<BaseKeyStore>

        beforeEach(() => {
            mockKeyStore = {
                getKey: jest.fn().mockResolvedValue(mockSessionKey),
                generateKey: jest.fn(),
                deleteKey: jest.fn(),
            } as unknown as jest.Mocked<BaseKeyStore>
        })

        it('should return RecordingEncryptor when running on cloud', () => {
            ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

            const encryptor = getBlockEncryptor(mockKeyStore)

            expect(encryptor).toBeInstanceOf(RecordingEncryptor)
        })

        it('should return PassthroughRecordingEncryptor when not running on cloud', () => {
            ;(envUtils.isCloud as jest.Mock).mockReturnValue(false)

            const encryptor = getBlockEncryptor(mockKeyStore)

            expect(encryptor).toBeInstanceOf(PassthroughRecordingEncryptor)
        })
    })
})
