/** Loads the anonymizer allow lists, failing safe to the in-binary defaults (never to "no scrubbing"). */
import { logger } from '~/common/utils/logger'

import { AllowLists } from './allow-lists'
import { defaultAllowLists } from './default-dict'

export interface RawAllowLists {
    text?: unknown
    url?: unknown
}

/** Fetches the raw `{ text, url }` allow-list document (e.g. from S3). */
export type AllowListFetcher = () => Promise<RawAllowLists>

// Bound an untrusted allow-list document so a malformed/huge file can't exhaust memory.
const MAX_ALLOW_LIST_ENTRIES = 500_000
const MAX_ALLOW_LIST_ENTRY_LEN = 256

function sanitizeEntries(raw: unknown): string[] {
    if (!Array.isArray(raw)) {
        return []
    }
    const entries = raw.filter((x): x is string => typeof x === 'string' && x.length <= MAX_ALLOW_LIST_ENTRY_LEN)
    return entries.length > MAX_ALLOW_LIST_ENTRIES ? entries.slice(0, MAX_ALLOW_LIST_ENTRIES) : entries
}

export function buildAllowLists(raw: RawAllowLists): AllowLists {
    return new AllowLists(sanitizeEntries(raw.text), sanitizeEntries(raw.url))
}

/** Load the allow lists once at startup, returning the in-binary defaults if there's no fetcher or it fails. */
export async function loadAllowLists(fetcher: AllowListFetcher | undefined): Promise<AllowLists> {
    if (!fetcher) {
        return defaultAllowLists()
    }
    try {
        const raw = await fetcher()
        return buildAllowLists(raw)
    } catch (error) {
        logger.warn('🙈', 'anonymize_allow_list_load_failed_using_defaults', { error: String(error) })
        return defaultAllowLists()
    }
}
