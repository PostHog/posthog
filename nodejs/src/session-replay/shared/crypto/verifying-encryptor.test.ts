import snappy from 'snappy'

import { RecordingDecryptor, RecordingEncryptor, SessionKey } from '../types'
import { CryptoMetrics } from './metrics'
import { VerifyingEncryptor } from './verifying-encryptor'

jest.mock('./metrics')
jest.mock('../../../utils/logger')

function createMockEncryptor(): jest.Mocked<RecordingEncryptor> {
    return {
        start: jest.fn().mockResolvedValue(undefined),
        encryptBlock: jest.fn().mockImplementation((_s, _t, buf) => Promise.resolve(buf)),
        encryptBlockWithKey: jest.fn().mockImplementation((_s, _t, buf) => buf),
    } as unknown as jest.Mocked<RecordingEncryptor>
}

function createMockDecryptor(): jest.Mocked<RecordingDecryptor> {
    return {
        start: jest.fn().mockResolvedValue(undefined),
        decryptBlock: jest.fn().mockImplementation((_s, _t, buf) => Promise.resolve(buf)),
        decryptBlockWithKey: jest.fn().mockImplementation((_s, _t, buf) => buf),
    } as unknown as jest.Mocked<RecordingDecryptor>
}

function makeValidBlock(): Buffer {
    const jsonl = JSON.stringify({ type: 3, data: {} }) + '\n'
    return snappy.compressSync(Buffer.from(jsonl))
}

const ciphertextKey: SessionKey = {
    plaintextKey: Buffer.from('test-key'),
    encryptedKey: Buffer.from('encrypted-key'),
    sessionState: 'ciphertext',
}

const cleartextKey: SessionKey = {
    plaintextKey: Buffer.alloc(0),
    encryptedKey: Buffer.alloc(0),
    sessionState: 'cleartext',
}

describe('VerifyingEncryptor', () => {
    let mockEncryptor: jest.Mocked<RecordingEncryptor>
    let mockDecryptor: jest.Mocked<RecordingDecryptor>

    beforeEach(() => {
        jest.clearAllMocks()
        mockEncryptor = createMockEncryptor()
        mockDecryptor = createMockDecryptor()
    })

    it('delegates start() to both encryptor and decryptor', async () => {
        const verifier = new VerifyingEncryptor(mockEncryptor, mockDecryptor, 0)
        await verifier.start()
        expect(mockEncryptor.start).toHaveBeenCalled()
        expect(mockDecryptor.start).toHaveBeenCalled()
    })

    it('delegates encryptBlock() to the wrapped encryptor', async () => {
        const verifier = new VerifyingEncryptor(mockEncryptor, mockDecryptor, 0)
        const buf = Buffer.from('data')
        await verifier.encryptBlock('s1', 1, buf)
        expect(mockEncryptor.encryptBlock).toHaveBeenCalledWith('s1', 1, buf)
    })

    it('passes through encrypted data unchanged', () => {
        const encrypted = Buffer.from('encrypted-output')
        mockEncryptor.encryptBlockWithKey.mockReturnValue(encrypted)
        const verifier = new VerifyingEncryptor(mockEncryptor, mockDecryptor, 0)

        const result = verifier.encryptBlockWithKey('s1', 1, makeValidBlock(), ciphertextKey)

        expect(result).toBe(encrypted)
    })

    it('does not verify when rate is 0', () => {
        const verifier = new VerifyingEncryptor(mockEncryptor, mockDecryptor, 0)
        verifier.encryptBlockWithKey('s1', 1, makeValidBlock(), ciphertextKey)
        expect(mockDecryptor.decryptBlockWithKey).not.toHaveBeenCalled()
    })

    it('skips verification for cleartext sessions', () => {
        jest.spyOn(Math, 'random').mockReturnValue(0)
        const verifier = new VerifyingEncryptor(mockEncryptor, mockDecryptor, 1.0)

        verifier.encryptBlockWithKey('s1', 1, makeValidBlock(), cleartextKey)

        expect(mockDecryptor.decryptBlockWithKey).not.toHaveBeenCalled()
        jest.spyOn(Math, 'random').mockRestore()
    })

    it('verifies on sampled blocks and increments success counter', () => {
        jest.spyOn(Math, 'random').mockReturnValue(0)
        const block = makeValidBlock()
        mockDecryptor.decryptBlockWithKey.mockReturnValue(block)
        const verifier = new VerifyingEncryptor(mockEncryptor, mockDecryptor, 1.0)

        verifier.encryptBlockWithKey('s1', 1, block, ciphertextKey)

        expect(mockDecryptor.decryptBlockWithKey).toHaveBeenCalled()
        expect(CryptoMetrics.incrementCryptoIntegrityChecks).toHaveBeenCalled()
        expect(CryptoMetrics.incrementCryptoIntegritySuccesses).toHaveBeenCalled()
        expect(CryptoMetrics.incrementCryptoIntegrityFailures).not.toHaveBeenCalled()
        jest.spyOn(Math, 'random').mockRestore()
    })

    it.each([
        {
            name: 'decrypted bytes differ from original',
            block: makeValidBlock(),
            expectedType: 'mismatch',
            setup: (dec: jest.Mocked<RecordingDecryptor>) => {
                dec.decryptBlockWithKey.mockReturnValue(Buffer.from('wrong'))
            },
        },
        {
            name: 'decrypted block is not valid snappy',
            block: Buffer.from('not-valid-snappy'),
            expectedType: 'decompression',
            setup: () => {},
        },
        {
            name: 'decrypted block contains invalid JSONL',
            block: snappy.compressSync(Buffer.from('not json\n')),
            expectedType: 'json_parse',
            setup: () => {},
        },
        {
            name: 'decryptor throws',
            block: makeValidBlock(),
            expectedType: 'exception',
            setup: (dec: jest.Mocked<RecordingDecryptor>) => {
                dec.decryptBlockWithKey.mockImplementation(() => {
                    throw new Error('decryption failed')
                })
            },
        },
    ])('increments failure counter with type=$expectedType when $name', ({ block, expectedType, setup }) => {
        jest.spyOn(Math, 'random').mockReturnValue(0)
        setup(mockDecryptor)
        const verifier = new VerifyingEncryptor(mockEncryptor, mockDecryptor, 1.0)

        verifier.encryptBlockWithKey('s1', 1, block, ciphertextKey)

        expect(CryptoMetrics.incrementCryptoIntegrityChecks).toHaveBeenCalled()
        expect(CryptoMetrics.incrementCryptoIntegrityFailures).toHaveBeenCalledWith(expectedType)
        expect(CryptoMetrics.incrementCryptoIntegritySuccesses).not.toHaveBeenCalled()
        jest.spyOn(Math, 'random').mockRestore()
    })

    it('does not throw when verification fails', () => {
        jest.spyOn(Math, 'random').mockReturnValue(0)
        mockDecryptor.decryptBlockWithKey.mockImplementation(() => {
            throw new Error('kaboom')
        })
        const verifier = new VerifyingEncryptor(mockEncryptor, mockDecryptor, 1.0)

        expect(() => {
            verifier.encryptBlockWithKey('s1', 1, makeValidBlock(), ciphertextKey)
        }).not.toThrow()
        jest.spyOn(Math, 'random').mockRestore()
    })
})
