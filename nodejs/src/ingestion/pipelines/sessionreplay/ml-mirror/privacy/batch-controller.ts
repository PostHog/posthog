import pLimit from 'p-limit'

import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { PipelineResult, PipelineResultType, ok } from '~/ingestion/framework/results'
import { MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'
import { usesRawSessionIdentifiers } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'
import {
    DeleteKeyResult,
    EncryptResult,
    KeyStore,
    RecordingEncryptor,
    SessionKey,
} from '~/ingestion/pipelines/sessionreplay/shared/types'

import { MlKeyEncryption, encryptEnvelope } from './crypto'
import { MlKeyBatch, MlSessionKeyStore, MlSessionKeys } from './key-store'
import { MlKeyIdentity, MlSessionIdentity } from './schema'

export interface MlRecordingKey extends SessionKey {
    mlIdentity: MlKeyIdentity
}

export class MlPrivacyBatchController implements KeyStore, RecordingEncryptor {
    private readonly publish = pLimit(8)
    private batch?: MlKeyBatch
    private deferred: Array<(sideEffects: (promises: Promise<unknown>[]) => Promise<void>) => Promise<void>> = []

    constructor(
        private readonly store: MlSessionKeyStore,
        private readonly encryption: MlKeyEncryption
    ) {}

    public async start(): Promise<void> {
        await this.encryption.start()
    }

    public stop(): void {
        this.encryption.clear()
    }

    public reset(): void {
        this.batch = undefined
        this.deferred = []
    }

    public async prepare(identities: MlSessionIdentity[]): Promise<void> {
        this.deferred = []
        const startedAt = performance.now()
        this.batch = await this.store.prepare(
            identities.filter((identity) => usesRawSessionIdentifiers(identity.sessionId))
        )
        MlMirrorMetrics.observeMlPrivacyPhase('prepare', performance.now() - startedAt)
    }

    public keys(teamId: number, sessionId: string): MlSessionKeys | undefined {
        return this.batch?.get(teamId, sessionId)
    }

    public defer<T extends { team: { teamId: number }; headers: { session_id: string }; sessionKey: SessionKey }>(
        input: T,
        action: (input: T) => Promise<PipelineResult<T>>
    ): Promise<PipelineResult<T>> {
        this.deferred.push(async (sideEffects) => {
            const key = await this.getKey(input.headers.session_id, input.team.teamId)
            if (key.sessionState !== 'deleted') {
                const result = await action({ ...input, sessionKey: key })
                if (result.type === PipelineResultType.OK) {
                    await sideEffects(result.sideEffects ?? [])
                }
            }
        })
        return Promise.resolve(ok(input))
    }

    // Delivery acks are handed to the consumer's scheduler, which drains before offsets commit, so publication runs at enqueue speed instead of one ack round trip per message.
    public async commit(scheduler?: PromiseScheduler): Promise<void> {
        if (!this.batch) {
            return
        }
        const startedAt = performance.now()
        await this.batch.commit()
        const committedAt = performance.now()
        MlMirrorMetrics.observeMlPrivacyPhase('commit', committedAt - startedAt)
        const sideEffects = async (promises: Promise<unknown>[]): Promise<void> => {
            if (!promises.length) {
                return
            }
            if (scheduler) {
                for (const promise of promises) {
                    void scheduler.schedule(promise)
                }
            } else {
                await Promise.all(promises)
            }
        }
        await Promise.all(this.deferred.map((action) => this.publish(() => action(sideEffects))))
        this.deferred = []
        MlMirrorMetrics.observeMlPrivacyPhase('publish', performance.now() - committedAt)
    }

    public getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        if (!usesRawSessionIdentifiers(sessionId)) {
            return Promise.resolve({
                sessionState: 'cleartext',
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
            })
        }
        const keys = this.keys(teamId, sessionId)
        if (!keys) {
            return Promise.resolve({
                sessionState: 'deleted',
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
            })
        }
        const key: MlRecordingKey = {
            sessionState: 'ciphertext',
            plaintextKey: keys.session.plaintext,
            encryptedKey: keys.session.wrapped,
            mlIdentity: keys.session.identity,
        }
        return Promise.resolve(key)
    }

    public generateKey(sessionId: string, teamId: number): Promise<SessionKey> {
        return this.getKey(sessionId, teamId)
    }

    public deleteKey(): Promise<DeleteKeyResult> {
        return Promise.reject(new Error('ML deletion requires the durable deletion workflow'))
    }

    public async encryptBlock(sessionId: string, teamId: number, data: Buffer): Promise<EncryptResult> {
        return this.encryptBlockWithKey(sessionId, teamId, data, await this.getKey(sessionId, teamId))
    }

    public encryptBlockWithKey(_sessionId: string, _teamId: number, data: Buffer, key: SessionKey): EncryptResult {
        if (key.sessionState === 'cleartext') {
            return { data, sessionState: 'cleartext' }
        }
        if (key.sessionState !== 'ciphertext' || !('mlIdentity' in key)) {
            throw new Error('ML block has no active encryption key')
        }
        const mlKey = key as MlRecordingKey
        return {
            data: encryptEnvelope(
                { identity: mlKey.mlIdentity, plaintext: key.plaintextKey, wrapped: key.encryptedKey },
                'rrweb',
                data
            ),
            sessionState: 'ciphertext',
        }
    }
}
