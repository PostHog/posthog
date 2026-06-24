import { AllowLists } from './allow-lists'

/** Replacement char for redacted (non-allow-listed) word characters. */
export const REDACT_CHAR = '*'
/** Replacement char for numeric tokens. */
export const NUMBER_CHAR = '#'
/** Strings with more than this many words are fully redacted (free-text guard). */
export const DEFAULT_MAX_WORDS_LEN = 8

/** A media image whose placeholder should be replaced by an async downscale-blur later. */
export interface BlurJob {
    attrs: Record<string, unknown>
    key: string
    dataUri: string
}

/** Per-scrub context: the active allow lists plus tunables read by the scrubbers. */
export interface ScrubContext {
    allow: AllowLists
    maxWordsLen: number
    /** Optional collector for deferred image-blur jobs (see {@link BlurJob}). */
    blurJobs?: BlurJob[]
}

/** Shared non-null-object type guard used across the scrubbers. */
export function isObject(v: unknown): v is Record<string, any> {
    return typeof v === 'object' && v !== null
}
