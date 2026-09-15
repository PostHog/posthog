import { usesRawSessionIdentifiers } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'
import { CleartextKeyStore } from '~/ingestion/pipelines/sessionreplay/shared/keystore/cleartext-keystore'
import { SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'

export class LegacyMlKeyStore extends CleartextKeyStore {
    public override getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        if (usesRawSessionIdentifiers(sessionId)) {
            throw new Error('ML v2 ingestion requires privacy configuration')
        }
        return super.getKey(sessionId, teamId)
    }

    public override generateKey(sessionId: string, teamId: number): Promise<SessionKey> {
        return this.getKey(sessionId, teamId)
    }
}
