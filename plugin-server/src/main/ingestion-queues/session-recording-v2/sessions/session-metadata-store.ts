import { randomUUID } from 'crypto'

import { status } from '../../../../utils/status'
import { SessionBlockMetadata } from './session-block-metadata'

export class SessionMetadataStore {
    constructor() {
        status.debug('🔍', 'session_metadata_store_created')
    }

    public async storeSessionBlock(metadata: SessionBlockMetadata): Promise<void> {
        // TODO: Implement storage of session block metadata
        status.debug('🔍', 'session_metadata_store_block_stored', {
            uuid: randomUUID(),
            session_id: metadata.sessionId,
            team_id: metadata.teamId,
            first_timestamp: metadata.startTimestamp,
            last_timestamp: metadata.endTimestamp,
            urls: ['https://app.posthog.com/events', 'https://app.posthog.com/insights'], // Fake URLs for now
        })
        return Promise.resolve()
    }
}
