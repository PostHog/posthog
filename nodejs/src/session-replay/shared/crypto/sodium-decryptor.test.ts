import sodium from 'libsodium-wrappers'

import { KeyStore, SessionKey, SessionKeyDeletedError } from '../types'
import { SodiumRecordingDecryptor } from './sodium-decryptor'
import { SodiumRecordingEncryptor } from './sodium-encryptor'

describe('SodiumRecordingDecryptor', () => {
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
        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)

        expect(decryptor).toBeInstanceOf(SodiumRecordingDecryptor)
    })

    it('should initialize sodium on start', async () => {
        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)
        await expect(decryptor.start()).resolves.toBeUndefined()
    })

    it('should decrypt cipherText using keyStore key', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)
        const clearText = Buffer.from('hello world')

        const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)
        const decrypted = await decryptor.decryptBlock('session-123', 1, encrypted)

        expect(mockKeyStore.getKey).toHaveBeenCalledWith('session-123', 1)
        expect(decrypted).toEqual(clearText)
    })

    it('should throw error if getKey fails', async () => {
        mockKeyStore.getKey.mockRejectedValue(new Error('Key not found'))
        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)

        await expect(decryptor.decryptBlock('session-123', 1, Buffer.from('test'))).rejects.toThrow('Key not found')
    })

    it('should throw error if decryption fails with wrong key', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const clearText = Buffer.from('hello world')
        const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)

        const wrongKey: SessionKey = {
            plaintextKey: Buffer.from([
                32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6,
                5, 4, 3, 2, 1,
            ]),
            encryptedKey: mockEncryptedKey,
            sessionState: 'ciphertext',
        }
        mockKeyStore.getKey.mockResolvedValue(wrongKey)

        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)

        await expect(decryptor.decryptBlock('session-123', 1, encrypted)).rejects.toThrow()
    })

    it('should handle empty buffer roundtrip', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)
        const clearText = Buffer.from('')

        const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)
        const decrypted = await decryptor.decryptBlock('session-123', 1, encrypted)

        expect(decrypted).toEqual(clearText)
    })

    it('should handle large buffer roundtrip', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)
        const clearText = Buffer.alloc(1024 * 1024, 'x')

        const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)
        const decrypted = await decryptor.decryptBlock('session-123', 1, encrypted)

        expect(decrypted).toEqual(clearText)
    })

    it('should handle binary data roundtrip', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)
        const binaryData = Buffer.from([0x00, 0x01, 0x02, 0xff, 0xfe, 0xfd])

        const encrypted = await encryptor.encryptBlock('session-123', 1, binaryData)
        const decrypted = await decryptor.decryptBlock('session-123', 1, encrypted)

        expect(decrypted).toEqual(binaryData)
    })

    it('should throw error if ciphertext is tampered', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)
        const clearText = Buffer.from('hello world')

        const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)
        encrypted[0] = encrypted[0] ^ 0xff

        await expect(decryptor.decryptBlock('session-123', 1, encrypted)).rejects.toThrow()
    })

    it('should throw error if ciphertext is truncated', async () => {
        const encryptor = new SodiumRecordingEncryptor(mockKeyStore)
        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)
        const clearText = Buffer.from('hello world')

        const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)
        const truncated = encrypted.subarray(0, encrypted.length - 5)

        await expect(decryptor.decryptBlock('session-123', 1, truncated)).rejects.toThrow()
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

        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)

        await expect(decryptor.decryptBlock('session-123', 1, Buffer.from('test'))).rejects.toThrow(
            SessionKeyDeletedError
        )
        await expect(decryptor.decryptBlock('session-123', 1, Buffer.from('test'))).rejects.toThrow(
            'Session key has been deleted for session session-123 team 1'
        )

        try {
            await decryptor.decryptBlock('session-123', 1, Buffer.from('test'))
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

        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)

        try {
            await decryptor.decryptBlock('session-123', 1, Buffer.from('test'))
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

        const decryptor = new SodiumRecordingDecryptor(mockKeyStore)
        const cipherText = Buffer.from('hello world')

        const result = await decryptor.decryptBlock('session-123', 1, cipherText)

        expect(result).toEqual(cipherText)
    })
})
