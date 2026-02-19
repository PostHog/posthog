import sodium from 'libsodium-wrappers'

import { KeyStore, SessionKey, SessionKeyDeletedError } from '../types'
import { SodiumRecordingEncryptor } from './sodium-encryptor'

describe('SodiumRecordingEncryptor', () => {
    beforeAll(async () => {
        await sodium.ready
    })

    const mockPlaintextKey = Buffer.from([
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30,
        31, 32,
    ])
    const mockEncryptedKey = Buffer.from([101, 102, 103, 104, 105])

    const mockSessionKey: SessionKey = {
        plaintextKey: mockPlaintextKey,
        encryptedKey: mockEncryptedKey,
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

    it('should create instance via constructor', () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)

        expect(encryptor).toBeInstanceOf(SodiumRecordingEncryptor)
    })

    it('should initialize sodium on start', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        await expect(encryptor.start()).resolves.toBeUndefined()
    })

    it('should encrypt clearText using keyStore key', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const clearText = Buffer.from('hello world')

        const result = await encryptor.encryptBlock('session-123', 1, clearText)

        expect(mockKeyStore.getKey).toHaveBeenCalledWith('session-123', 1)
        expect(result).toBeInstanceOf(Buffer)
        expect(result.length).toBeGreaterThan(0)
        expect(result).not.toEqual(clearText)
    })

    it('should throw error if getKey fails', async () => {
        mockKeyStore.getKey.mockRejectedValue(new Error('Key not found'))
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)

        await expect(encryptor.encryptBlock('session-123', 1, Buffer.from('test'))).rejects.toThrow('Key not found')
    })

    it('should handle empty buffer', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const clearText = Buffer.from('')

        const result = await encryptor.encryptBlock('session-123', 1, clearText)

        expect(result).toBeInstanceOf(Buffer)
        expect(result.length).toBeGreaterThan(0)
    })

    it('should handle large buffer', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const clearText = Buffer.alloc(1024 * 1024, 'x')

        const result = await encryptor.encryptBlock('session-123', 1, clearText)

        expect(result).toBeInstanceOf(Buffer)
        expect(result.length).toBeGreaterThan(clearText.length)
    })

    it('should produce different output for same input due to random nonce', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const clearText = Buffer.from('hello world')

        const result1 = await encryptor.encryptBlock('session-123', 1, clearText)
        const result2 = await encryptor.encryptBlock('session-123', 1, clearText)

        // Each encryption uses a random nonce, so outputs should be different
        expect(result1).not.toEqual(result2)
        // But they should have the same length (nonce + ciphertext + auth tag)
        expect(result1.length).toEqual(result2.length)
    })

    it('should handle binary data', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
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
            sessionState: 'deleted',
            deletedAt,
        }
        mockKeyStore.getKey.mockResolvedValue(deletedSessionKey)

        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)

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

    it('should throw SessionKeyDeletedError with undefined deletedAt when not available', async () => {
        const deletedSessionKey: SessionKey = {
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            sessionState: 'deleted',
        }
        mockKeyStore.getKey.mockResolvedValue(deletedSessionKey)

        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)

        try {
            await encryptor.encryptBlock('session-123', 1, Buffer.from('test'))
        } catch (error) {
            expect(error).toBeInstanceOf(SessionKeyDeletedError)
            expect((error as SessionKeyDeletedError).deletedAt).toBeUndefined()
        }
    })

    it('should return data unchanged when session state is cleartext', async () => {
        const cleartextSessionKey: SessionKey = {
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            sessionState: 'cleartext',
        }
        mockKeyStore.getKey.mockResolvedValue(cleartextSessionKey)

        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const clearText = Buffer.from('hello world')

        const result = await encryptor.encryptBlock('session-123', 1, clearText)

        expect(result).toEqual(clearText)
    })
})
