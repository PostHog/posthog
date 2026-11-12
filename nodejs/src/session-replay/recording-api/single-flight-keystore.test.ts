import { SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'

import { SingleFlightKeyStore } from './single-flight-keystore'

describe('SingleFlightKeyStore', () => {
    const key = (n: number): SessionKey => ({
        plaintextKey: Buffer.from([n]),
        encryptedKey: Buffer.from([n]),
        sessionState: 'ciphertext',
    })

    const delegateWithHeldFirstRead = (...later: SessionKey[]): { delegate: any; release: (k: SessionKey) => void } => {
        let release: (k: SessionKey) => void = () => {}
        const getKey = jest.fn().mockImplementationOnce(() => new Promise<SessionKey>((resolve) => (release = resolve)))
        later.forEach((k) => getKey.mockResolvedValueOnce(k))
        const delegate = {
            start: jest.fn(),
            stop: jest.fn(),
            generateKey: jest.fn(),
            deleteKey: jest.fn().mockResolvedValue({ deleted: true }),
            getKey,
        }
        return { delegate, release: (k) => release(k) }
    }

    it('shares one key store read among concurrent lookups for a session, and reads again once it settles', async () => {
        const { delegate, release } = delegateWithHeldFirstRead(key(2), key(3))
        const store = new SingleFlightKeyStore(delegate)

        const parallel = [store.getKey('s1', 1), store.getKey('s1', 1), store.getKey('s1', 1)]
        const otherSession = await store.getKey('s2', 1)
        release(key(1))

        expect(await Promise.all(parallel)).toEqual([key(1), key(1), key(1)])
        expect(otherSession).toEqual(key(2))
        expect(await store.getKey('s1', 1)).toEqual(key(3))
        expect(delegate.getKey).toHaveBeenCalledTimes(3)
    })

    it('does not let a lookup made after a delete join one that started before it', async () => {
        const deleted: SessionKey = { ...key(0), sessionState: 'deleted' }
        const { delegate, release } = delegateWithHeldFirstRead(deleted)
        const store = new SingleFlightKeyStore(delegate)

        const before = store.getKey('s1', 1)
        await store.deleteKey('s1', 1, 'user')
        const after = await store.getKey('s1', 1)
        release(key(1))

        expect(after).toEqual(deleted)
        expect(await before).toEqual(key(1))
    })
})
