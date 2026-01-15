import sodium from 'libsodium-wrappers'

import * as envUtils from '../utils/env-utils'
import { BaseKeyStore, SessionKey } from './keystore'
import {
    BaseRecordingDecryptor,
    BaseRecordingEncryptor,
    PassthroughRecordingDecryptor,
    PassthroughRecordingEncryptor,
    RecordingDecryptor,
    RecordingEncryptor,
    getBlockDecryptor,
    getBlockEncryptor,
} from './recording-io'

jest.mock('../utils/env-utils', () => ({
    ...jest.requireActual('../utils/env-utils'),
    isCloud: jest.fn(),
}))

describe('recording-io', () => {
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
        encryptedSession: true,
    }

    describe('PassthroughRecordingEncryptor', () => {
        let mockKeyStore: jest.Mocked<BaseKeyStore>

        beforeEach(() => {
            mockKeyStore = {
                start: jest.fn(),
                getKey: jest.fn(),
                generateKey: jest.fn(),
                deleteKey: jest.fn(),
                destroy: jest.fn(),
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

    describe('PassthroughRecordingDecryptor', () => {
        let mockKeyStore: jest.Mocked<BaseKeyStore>

        beforeEach(() => {
            mockKeyStore = {
                start: jest.fn(),
                getKey: jest.fn(),
                generateKey: jest.fn(),
                deleteKey: jest.fn(),
                destroy: jest.fn(),
            } as unknown as jest.Mocked<BaseKeyStore>
        })

        it('should complete start without error', async () => {
            const decryptor = new PassthroughRecordingDecryptor(mockKeyStore)
            await expect(decryptor.start()).resolves.toBeUndefined()
        })

        it('should return cipherText unchanged', async () => {
            const decryptor = new PassthroughRecordingDecryptor(mockKeyStore)
            const cipherText = Buffer.from('encrypted data')

            const result = await decryptor.decryptBlock('session-123', 1, cipherText)

            expect(result).toEqual(cipherText)
        })

        it('should extend BaseRecordingDecryptor', () => {
            const decryptor = new PassthroughRecordingDecryptor(mockKeyStore)
            expect(decryptor).toBeInstanceOf(BaseRecordingDecryptor)
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
    })

    describe('RecordingDecryptor', () => {
        let mockKeyStore: jest.Mocked<BaseKeyStore>

        beforeEach(() => {
            mockKeyStore = {
                getKey: jest.fn().mockResolvedValue(mockSessionKey),
                generateKey: jest.fn(),
                deleteKey: jest.fn(),
            } as unknown as jest.Mocked<BaseKeyStore>
        })

        it('should create instance via constructor', () => {
            const decryptor = new RecordingDecryptor(mockKeyStore)

            expect(decryptor).toBeInstanceOf(RecordingDecryptor)
            expect(decryptor).toBeInstanceOf(BaseRecordingDecryptor)
        })

        it('should initialize sodium on start', async () => {
            const decryptor = new RecordingDecryptor(mockKeyStore)
            await expect(decryptor.start()).resolves.toBeUndefined()
        })

        it('should decrypt cipherText using keyStore key', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const decryptor = new RecordingDecryptor(mockKeyStore)
            const clearText = Buffer.from('hello world')

            const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)
            const decrypted = await decryptor.decryptBlock('session-123', 1, encrypted)

            expect(mockKeyStore.getKey).toHaveBeenCalledWith('session-123', 1)
            expect(decrypted).toEqual(clearText)
        })

        it('should throw error if getKey fails', async () => {
            mockKeyStore.getKey.mockRejectedValue(new Error('Key not found'))
            const decryptor = new RecordingDecryptor(mockKeyStore)

            await expect(decryptor.decryptBlock('session-123', 1, Buffer.from('test'))).rejects.toThrow('Key not found')
        })

        it('should throw error if decryption fails with wrong key', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const clearText = Buffer.from('hello world')
            const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)

            const wrongKey: SessionKey = {
                plaintextKey: Buffer.from([
                    32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7,
                    6, 5, 4, 3, 2, 1,
                ]),
                encryptedKey: mockEncryptedKey,
                nonce: mockNonce,
                encryptedSession: true,
            }
            mockKeyStore.getKey.mockResolvedValue(wrongKey)

            const decryptor = new RecordingDecryptor(mockKeyStore)

            await expect(decryptor.decryptBlock('session-123', 1, encrypted)).rejects.toThrow()
        })

        it('should handle empty buffer roundtrip', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const decryptor = new RecordingDecryptor(mockKeyStore)
            const clearText = Buffer.from('')

            const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)
            const decrypted = await decryptor.decryptBlock('session-123', 1, encrypted)

            expect(decrypted).toEqual(clearText)
        })

        it('should handle large buffer roundtrip', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const decryptor = new RecordingDecryptor(mockKeyStore)
            const clearText = Buffer.alloc(1024 * 1024, 'x')

            const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)
            const decrypted = await decryptor.decryptBlock('session-123', 1, encrypted)

            expect(decrypted).toEqual(clearText)
        })

        it('should handle binary data roundtrip', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const decryptor = new RecordingDecryptor(mockKeyStore)
            const binaryData = Buffer.from([0x00, 0x01, 0x02, 0xff, 0xfe, 0xfd])

            const encrypted = await encryptor.encryptBlock('session-123', 1, binaryData)
            const decrypted = await decryptor.decryptBlock('session-123', 1, encrypted)

            expect(decrypted).toEqual(binaryData)
        })

        it('should throw error if ciphertext is tampered', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const decryptor = new RecordingDecryptor(mockKeyStore)
            const clearText = Buffer.from('hello world')

            const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)
            encrypted[0] = encrypted[0] ^ 0xff

            await expect(decryptor.decryptBlock('session-123', 1, encrypted)).rejects.toThrow()
        })

        it('should throw error if ciphertext is truncated', async () => {
            const encryptor = new RecordingEncryptor(mockKeyStore)
            const decryptor = new RecordingDecryptor(mockKeyStore)
            const clearText = Buffer.from('hello world')

            const encrypted = await encryptor.encryptBlock('session-123', 1, clearText)
            const truncated = encrypted.subarray(0, encrypted.length - 5)

            await expect(decryptor.decryptBlock('session-123', 1, truncated)).rejects.toThrow()
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

    describe('getBlockDecryptor', () => {
        let mockKeyStore: jest.Mocked<BaseKeyStore>

        beforeEach(() => {
            mockKeyStore = {
                getKey: jest.fn().mockResolvedValue(mockSessionKey),
                generateKey: jest.fn(),
                deleteKey: jest.fn(),
            } as unknown as jest.Mocked<BaseKeyStore>
        })

        it('should return RecordingDecryptor when running on cloud', () => {
            ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

            const decryptor = getBlockDecryptor(mockKeyStore)

            expect(decryptor).toBeInstanceOf(RecordingDecryptor)
        })

        it('should return PassthroughRecordingDecryptor when not running on cloud', () => {
            ;(envUtils.isCloud as jest.Mock).mockReturnValue(false)

            const decryptor = getBlockDecryptor(mockKeyStore)

            expect(decryptor).toBeInstanceOf(PassthroughRecordingDecryptor)
        })
    })
})
