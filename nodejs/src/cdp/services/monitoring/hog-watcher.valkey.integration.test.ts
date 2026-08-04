import Redis from 'ioredis'

const host = process.env.CDP_VALKEY_HOST ?? '127.0.0.1'
const port = Number(process.env.CDP_VALKEY_PORT ?? 6390)

describe('Valkey cluster behavior', () => {
    let valkey: Redis.Redis

    beforeAll(async () => {
        valkey = new Redis(port, host, { maxRetriesPerRequest: 1 })
        await valkey.ping()
    })

    afterAll(async () => {
        await valkey.quit()
    })

    it('rejects MGET for keys in different slots', async () => {
        await expect(valkey.mget('valkey-test:first', 'valkey-test:second')).rejects.toThrow('CROSSSLOT')
    })

    it('pipelines individual GETs across slots and preserves ordering', async () => {
        await valkey.set('valkey-test:first', 'first')
        await valkey.set('valkey-test:second', 'second')

        await expect(valkey.pipeline().get('valkey-test:second').get('valkey-test:first').exec()).resolves.toEqual([
            [null, 'second'],
            [null, 'first'],
        ])
    })

    it('allows MGET when keys share a hash tag', async () => {
        await valkey.mset('valkey-test:{same}:first', 'first', 'valkey-test:{same}:second', 'second')
        await expect(valkey.mget('valkey-test:{same}:first', 'valkey-test:{same}:second')).resolves.toEqual([
            'first',
            'second',
        ])
    })
})
