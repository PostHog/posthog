import { KeyStore, RecordingEncryptor } from './types'

export function createMockKeyStore(): jest.Mocked<KeyStore> {
    return {
        start: jest.fn().mockResolvedValue(undefined),
        generateKey: jest.fn().mockResolvedValue({
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            sessionState: 'cleartext',
        }),
        getKey: jest.fn().mockResolvedValue({
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            sessionState: 'cleartext',
        }),
        deleteKey: jest.fn().mockResolvedValue({ deleted: true }),
        stop: jest.fn().mockResolvedValue(undefined),
    } as unknown as jest.Mocked<KeyStore>
}

export function createMockEncryptor(): jest.Mocked<RecordingEncryptor> {
    return {
        start: jest.fn().mockResolvedValue(undefined),
        encryptBlock: jest.fn().mockImplementation((_sessionId, _teamId, buffer) => Promise.resolve(buffer)),
        encryptBlockWithKey: jest.fn().mockImplementation((_sessionId, _teamId, buffer, _sessionKey) => buffer),
    } as unknown as jest.Mocked<RecordingEncryptor>
}
