import { DateTime } from 'luxon'

import { DB } from '../../utils/db/db'
import { UUIDT } from '../../utils/utils'

// This class is responsible for creating/updating a single person through the process-event pipeline
export class PersonStateManager {
    timestamp: DateTime
    newUuid: string

    private db: DB

    constructor(timestamp: DateTime, db: DB) {
        this.timestamp = timestamp
        this.newUuid = new UUIDT().toString()

        this.db = db
    }
}
