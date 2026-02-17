import { KeyStore } from '../types'
import { CleartextRecordingDecryptor } from './cleartext-decryptor'

describe('CleartextRecordingDecryptor', () => {
    let mockKeyStore: jest.Mocked<KeyStore>

    beforeEach(() => {
        mockKeyStore = {
            start: jest.fn(),
            getKey: jest.fn(),
            generateKey: jest.fn(),
            deleteKey: jest.fn(),
            stop: jest.fn(),
        } as unknown as jest.Mocked<KeyStore>
    })

    it('should complete start without error', async () => {
        const decryptor = new CleartextRecordingDecryptor(mockKeyStore)
        await expect(decryptor.start()).resolves.toBeUndefined()
    })

    it('should return cipherText unchanged', async () => {
        const decryptor = new CleartextRecordingDecryptor(mockKeyStore)
        const cipherText = Buffer.from('encrypted data')

        const result = await decryptor.decryptBlock('session-123', 1, cipherText)

        expect(result).toEqual(cipherText)
    })

    it('should return data unchanged in decryptBlockWithKey', () => {
        const decryptor = new CleartextRecordingDecryptor(mockKeyStore)
        const blockData = Buffer.from('some data')
        const mockSessionKey = {
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            sessionState: 'cleartext' as const,
        }

        const result = decryptor.decryptBlockWithKey('session-123', 1, blockData, mockSessionKey)

        expect(result).toEqual(blockData)
    })
})
