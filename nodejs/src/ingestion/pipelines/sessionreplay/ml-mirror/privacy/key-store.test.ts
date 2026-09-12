import { BatchGetItemCommand, DynamoDBClient, TransactWriteItemsCommand } from '@aws-sdk/client-dynamodb'
import { GenerateDataKeyCommand, KMSClient } from '@aws-sdk/client-kms'

import { MlKeyEncryption } from './crypto'
import { DynamoItem, MlPrivacyDynamoDB, encodeKey } from './dynamodb'
import { MlSessionKeyStore } from './key-store'
import { MlKeyReader } from './reader'
import { MlSessionIdentity, consentKeyId, distinctBlockId, imageKeyId, sessionKeyId, tableKeyString } from './schema'

const session: MlSessionIdentity = {
    teamId: 7,
    organizationId: 'organization-test',
    sessionId: '01994569-4380-7000-8000-000000000007',
    distinctId: 'anonymous-test',
}
const startedAt = Number.parseInt(session.sessionId.slice(0, 8) + session.sessionId.slice(9, 13), 16)
const table = 'ml-privacy-test'

class DynamoBoundary {
    public readonly items = new Map<string, DynamoItem>()
    public readSizes: number[] = []
    public writeSizes: number[] = []

    public send(command: BatchGetItemCommand | TransactWriteItemsCommand): Promise<object> {
        if (command instanceof BatchGetItemCommand) {
            const keys = command.input.RequestItems![table].Keys!
            this.readSizes.push(keys.length)
            return Promise.resolve({
                Responses: {
                    [table]: keys.flatMap((key) => {
                        const value = this.items.get(JSON.stringify([key.pk.S, key.sk.S]))
                        return value ? [value] : []
                    }),
                },
            })
        }
        const actions = command.input.TransactItems!
        this.writeSizes.push(actions.length)
        for (const action of actions) {
            const operation = action.ConditionCheck ?? action.Put!
            const key = 'Item' in operation ? operation.Item! : operation.Key!
            const current = this.items.get(JSON.stringify([key.pk.S, key.sk.S]))
            const condition = operation.ConditionExpression
            const values = operation.ExpressionAttributeValues
            const valid =
                !condition ||
                (condition === 'attribute_not_exists(pk)'
                    ? !current
                    : condition === 'allowed = :allowed AND granted_at = :grant'
                      ? current?.allowed.BOOL === true && current?.granted_at.N === values![':grant'].N
                      : condition === 'attribute_exists(wrapped_key) AND attribute_not_exists(deleted)'
                        ? current?.wrapped_key?.B && !current?.deleted
                        : false)
            if (!valid) {
                throw new Error('Conditional transaction failed')
            }
        }
        for (const action of actions) {
            if (action.Put) {
                const item = action.Put.Item!
                this.items.set(JSON.stringify([item.pk.S, item.sk.S]), item)
            }
        }
        return Promise.resolve({})
    }
}

describe('ML session key batches', () => {
    let boundary: DynamoBoundary
    let encryption: MlKeyEncryption
    let store: MlSessionKeyStore
    let reader: MlKeyReader
    let generated: number

    beforeEach(async () => {
        boundary = new DynamoBoundary()
        generated = 0
        encryption = new MlKeyEncryption(
            {
                send: jest.fn((command) => {
                    if (command instanceof GenerateDataKeyCommand) {
                        const bytes = Buffer.alloc(32, ++generated)
                        return Promise.resolve({ Plaintext: bytes, CiphertextBlob: bytes })
                    }
                    return Promise.resolve({ Plaintext: command.input.CiphertextBlob })
                }),
            } as unknown as KMSClient,
            'test-key',
            1000,
            60000,
            8,
            1_000_000_000
        )
        await encryption.start()
        const db = new MlPrivacyDynamoDB(boundary as unknown as DynamoDBClient, table)
        store = new MlSessionKeyStore(db, encryption)
        reader = new MlKeyReader(db, encryption)
        const key = consentKeyId(session.organizationId)
        boundary.items.set(tableKeyString(key), {
            ...encodeKey(key),
            allowed: { BOOL: true },
            granted_at: { N: String(startedAt - 100) },
        })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('records every distinct ID before making a session available to later batches', async () => {
        const identities = Array.from({ length: 120 }, (_, index) => ({ ...session, distinctId: `person-${index}` }))
        const batch = await store.prepare(identities)
        expect(generated).toBe(2)
        await batch.commit()
        expect([...boundary.items.values()].filter((item) => item.forward_pk).length).toBe(120)
        expect(Math.max(...boundary.readSizes)).toBeLessThanOrEqual(100)
        expect(Math.max(...boundary.writeSizes)).toBeLessThanOrEqual(100)
        expect((await reader.read([sessionKeyId(session.teamId, session.sessionId)])).size).toBe(1)
    })

    it('adopts a competing writer key after the conditional write fails', async () => {
        const first = await store.prepare([session])
        const second = await store.prepare([session])
        const provisional = second.get(session.teamId, session.sessionId)!.session.plaintext
        await first.commit()
        jest.useFakeTimers()
        const committing = second.commit()
        await jest.runAllTimersAsync()
        await committing
        expect(second.get(session.teamId, session.sessionId)!.session.plaintext).toEqual(
            first.get(session.teamId, session.sessionId)!.session.plaintext
        )
        expect(second.get(session.teamId, session.sessionId)!.session.plaintext).not.toEqual(provisional)
    })

    it('blocks the whole session when any of its distinct IDs is deleted', async () => {
        const first = await store.prepare([session])
        await first.commit()
        const blocked = distinctBlockId(session.teamId, 'identified-test')
        boundary.items.set(tableKeyString(blocked), { ...encodeKey(blocked), deleted: { BOOL: true } })
        const next = await store.prepare([session, { ...session, distinctId: 'identified-test' }])
        expect(next.get(session.teamId, session.sessionId)).toBeUndefined()
        await next.commit()
        expect((await reader.read([sessionKeyId(session.teamId, session.sessionId)])).size).toBe(0)
        expect((await reader.read([imageKeyId(session.teamId, startedAt - 100)])).size).toBe(1)
    })

    it('rejects old sessions after re-consent and does not trust cached keys after withdrawal', async () => {
        const first = await store.prepare([session])
        await first.commit()
        const consent = boundary.items.get(tableKeyString(consentKeyId(session.organizationId)))!
        consent.allowed = { BOOL: false }
        expect((await reader.read([sessionKeyId(session.teamId, session.sessionId)])).size).toBe(0)
        consent.allowed = { BOOL: true }
        consent.granted_at = { N: String(startedAt + 1) }
        const next = await store.prepare([session])
        expect(next.get(session.teamId, session.sessionId)).toBeUndefined()
        await next.commit()
        expect((await reader.read([sessionKeyId(session.teamId, session.sessionId)])).size).toBe(0)
    })
})
