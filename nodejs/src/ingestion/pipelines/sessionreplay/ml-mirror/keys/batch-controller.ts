import { ML_BLOCK_COMPRESSION } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-compression'
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
import { MlKeyBatch, MlSessionKeyStore } from './key-store'
import { MlKeyIdentity, MlSessionIdentity } from './schema'

export interface MlRecordingKey extends SessionKey {
    mlIdentity: MlKeyIdentity
}

const CLEARTEXT_KEY: SessionKey = {
    sessionState: 'cleartext',
    plaintextKey: Buffer.alloc(0),
    encryptedKey: Buffer.alloc(0),
}

const DELETED_KEY: SessionKey = {
    sessionState: 'deleted',
    plaintextKey: Buffer.alloc(0),
    encryptedKey: Buffer.alloc(0),
}

export class MlKeyBatchController implements KeyStore, RecordingEncryptor {
    // The session resolution stage resolves keys through the KeyStore interface, which names no batch, so it reads the batch prepared last. That stage runs one batch at a time, so the batch prepared last is the one it is resolving.
    private resolving?: MlKeyBatch

    constructor(
        private readonly store: MlSessionKeyStore,
        private readonly encryption: MlKeyEncryption
    ) {}

    public start(): Promise<void> {
        return Promise.resolve()
    }

    public stop(): void {
        this.encryption.clear()
    }

    public async prepare(identities: MlSessionIdentity[]): Promise<MlKeyBatch> {
        const startedAt = performance.now()
        const batch = await this.store.prepare(
            identities.filter((identity) => usesRawSessionIdentifiers(identity.sessionId))
        )
        MlMirrorMetrics.observeMlKeyPhase('prepare', performance.now() - startedAt)
        this.resolving = batch
        return batch
    }

    public async commit(batch: MlKeyBatch): Promise<void> {
        const startedAt = performance.now()
        await batch.commit()
        MlMirrorMetrics.observeMlKeyPhase('commit', performance.now() - startedAt)
    }

    public sessionKey(batch: MlKeyBatch | undefined, sessionId: string, teamId: number): SessionKey {
        if (!usesRawSessionIdentifiers(sessionId)) {
            return CLEARTEXT_KEY
        }
        const keys = batch?.get(teamId, sessionId)
        if (!keys) {
            return DELETED_KEY
        }
        const key: MlRecordingKey = {
            sessionState: 'ciphertext',
            plaintextKey: keys.session.plaintext,
            encryptedKey: keys.session.wrapped,
            mlIdentity: keys.session.identity,
        }
        return key
    }

    public getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        return Promise.resolve(this.sessionKey(this.resolving, sessionId, teamId))
    }

    public generateKey(sessionId: string, teamId: number): Promise<SessionKey> {
        return this.getKey(sessionId, teamId)
    }

    public deleteKey(): Promise<DeleteKeyResult> {
        return Promise.reject(new Error('ML deletion requires the durable deletion workflow'))
    }

    // Batches overlap, so the batch that prepared last owns no particular session. A block carries the key the session was recorded with.
    public encryptBlock(_sessionId: string, _teamId: number, _data: Buffer): Promise<EncryptResult> {
        return Promise.reject(
            new Error('ML blocks need the key recorded on the session, so encryptBlockWithKey is required')
        )
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
                data,
                { codec: ML_BLOCK_COMPRESSION.codec }
            ),
            sessionState: 'ciphertext',
        }
    }
}
