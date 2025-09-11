import { CursorUtils, UtilsExtension } from '@posthog/plugin-scaffold'

import { Hub } from '../../../types'
import { postgresIncrement, postgresSetOnce } from '../utils'

// These are not utils for internal use!
// These are general utility functions passed as utils in the plugin meta
export function createUtils(server: Hub, pluginConfigId: number): UtilsExtension {
    // Safe cursor utils for multi-threaded applications
    const cursor: CursorUtils = {
        init: async function (key, initialValue) {
            if (!initialValue) {
                initialValue = 0
            }
            if (typeof initialValue !== 'number') {
                throw new Error(`The cursor's initial value must be a number!`)
            }
            await postgresSetOnce(server.db, pluginConfigId, key, initialValue)
        },
        increment: async function (key, incrementBy) {
            if (!incrementBy) {
                incrementBy = 1
            }
            if (typeof incrementBy !== 'number') {
                throw new Error(`The incrementBy value must be a number!`)
            }
            const cursor = await postgresIncrement(server.db, pluginConfigId, key, incrementBy)
            return Number(cursor)
        },
    }

    return {
        cursor,
    }
}
