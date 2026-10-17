import { GetItemCommand } from '@aws-sdk/client-dynamodb'
import { DecryptCommand } from '@aws-sdk/client-kms'

import vector from '~/ingestion/pipelines/sessionreplay/ml-mirror/keys/encryption-vector-v4.json'

import { V4FrameContext, sealV4Frame } from './frame'
import { TeamDayKeys, teamDayWrappingContext } from './team-day-keys'

const base64 = (value: string): Buffer => Buffer.from(value, 'base64')

describe('v4 keys', () => {
    it.each([
        [
            'an image under the team day key',
            vector.teamDayKey,
            vector.image.context,
            vector.image.bytes,
            vector.image.nonce,
            vector.image.frame,
        ],
        [
            'a fetched image under the team day key',
            vector.teamDayKey,
            vector.imageUrl.context,
            vector.imageUrl.bytes,
            vector.imageUrl.nonce,
            vector.imageUrl.frame,
        ],
        [
            'a block under the session key',
            vector.sessionKey,
            vector.block.context,
            vector.block.body,
            vector.block.nonce,
            vector.block.frame,
        ],
    ])('seals %s exactly as the Rust recorder does', (_name, key, context, body, nonce, frame) => {
        // The Rust crate pins the same file, so the two writers cannot drift apart.
        expect(sealV4Frame(base64(key), context as V4FrameContext, base64(body), base64(nonce))).toEqual(base64(frame))
    })

    const TEAM = 7
    const DAY = '2026-10-15'
    const wrapped = Buffer.from('wrapped')
    const stored = { pk: { S: 'team:7' }, sk: { S: `day:${DAY}` }, wrapped_key: { B: wrapped } }

    function fakes(row: Record<string, any> | undefined, kmsRequestsPerSecond?: number, readBudgetMs?: number) {
        const dynamo = {
            send: jest.fn((command: unknown) => {
                if (command instanceof GetItemCommand) {
                    return Promise.resolve({ Item: row })
                }
                throw new Error('the fetcher never writes a key row')
            }),
        }
        const kms = {
            send: jest.fn((command: unknown) => {
                if (command instanceof DecryptCommand) {
                    expect(command.input.EncryptionContext).toEqual(teamDayWrappingContext(TEAM, DAY))
                    return Promise.resolve({ Plaintext: Buffer.alloc(32, 2) })
                }
                throw new Error('the fetcher never generates a key')
            }),
        }
        return { keys: new TeamDayKeys(dynamo, kms, 'table', 'arn', kmsRequestsPerSecond, readBudgetMs), dynamo, kms }
    }

    it.each([
        ['unwraps a stored key', stored, { status: 'ok', key: Buffer.alloc(32, 2) }, 1],
        // The recorder stores the row before it sends a URL, so no row means it expired: nothing is minted.
        ['finds no key for a day without a row, and reads again next time', undefined, { status: 'missing' }, 2],
        ['holds a tombstone', { ...stored, wrapped_key: undefined, deleted: { BOOL: true } }, { status: 'deleted' }, 1],
    ])('%s', async (_name, row, expected, reads) => {
        const { keys, dynamo } = fakes(row)
        expect(await keys.get(TEAM, DAY)).toEqual(expected)
        expect(await keys.get(TEAM, DAY)).toEqual(expected)
        expect(dynamo.send).toHaveBeenCalledTimes(reads)
    })

    it('gives up within its budget while it waits for a KMS turn, and makes no KMS call after that', async () => {
        // One request a minute: the first lookup takes the only slot, the next ones wait on the rate limit or the queue.
        const { keys, kms } = fakes(stored, 1 / 60, 50)
        const days = [DAY, ...Array.from({ length: 11 }, (_, day) => `2026-09-${String(day + 1).padStart(2, '0')}`)]
        const lookups = days.map((day) => keys.get(TEAM, day))

        const settled = await Promise.allSettled(lookups)
        await new Promise((resolve) => setImmediate(resolve))

        expect(settled.map((lookup) => lookup.status)).toEqual(['fulfilled', ...Array(11).fill('rejected')])
        expect(kms.send).toHaveBeenCalledTimes(1)
    })
})
