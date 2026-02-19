import { KeyStore } from '../types'
import { CleartextRecordingEncryptor } from './cleartext-encryptor'

describe('CleartextRecordingEncryptor', () => {
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
        const encryptor = new CleartextRecordingEncryptor(mockKeyStore)
        await expect(encryptor.start()).resolves.toBeUndefined()
    })

    it('should return clearText unchanged', async () => {
        const encryptor = new CleartextRecordingEncryptor(mockKeyStore)
        const clearText = Buffer.from('hello world')

        const result = await encryptor.encryptBlock('session-123', 1, clearText)

        expect(result).toEqual(clearText)
    })

    it('should return data unchanged in encryptBlockWithKey', () => {
        const encryptor = new CleartextRecordingEncryptor(mockKeyStore)
        const blockData = Buffer.from('some data')
        const mockSessionKey = {
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            sessionState: 'cleartext' as const,
        }

        const result = encryptor.encryptBlockWithKey('session-123', 1, blockData, mockSessionKey)

        expect(result).toEqual(blockData)
    })
})
