import { CleartextKeyStore } from '@posthog/replay-storage/keystore/cleartext-keystore'
import { SessionKey } from '@posthog/replay-storage/types'

import { usesRawSessionIdentifiers } from '~/pipelines/ml-mirror/session-identifier-format'

export class LegacyMlKeyStore extends CleartextKeyStore {
    public override getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        if (usesRawSessionIdentifiers(sessionId)) {
            throw new Error('ML v2 ingestion requires key manager configuration')
        }
        return super.getKey(sessionId, teamId)
    }

    public override generateKey(sessionId: string, teamId: number): Promise<SessionKey> {
        return this.getKey(sessionId, teamId)
    }
}
