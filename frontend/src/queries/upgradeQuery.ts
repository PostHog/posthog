import api from 'lib/api'
import { isTransientServerError } from 'lib/api-error'

import { Node } from '~/queries/schema/schema-general'
import { checkLatestVersionsOnQuery } from '~/queries/utils'

/**
 * Migrates a query to the latest schema version through the API, and returns `null` when that
 * request fails. A caller that keeps the saved query on `null` still renders it, so one failed
 * upgrade cannot blank a whole notebook or insight scene.
 *
 * A transient gateway failure is retried once, because the upgrade is a pure schema rewrite and
 * the same request usually succeeds. A 4xx and a plain 500 are deterministic, so they are not.
 */
export async function upgradeQueryToLatestVersion(query: Node): Promise<Node | null> {
    if (checkLatestVersionsOnQuery(query)) {
        return query
    }

    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            return (await api.schema.queryUpgrade({ query })).query
        } catch (error) {
            if (attempt > 0 || !isTransientServerError(error)) {
                break
            }
        }
    }

    return null
}
