import { AllowLists } from './allow-lists'

/** Replacement char for redacted (non-allow-listed) word characters. */
export const REDACT_CHAR = '*'
/** Replacement char for numeric tokens. */
export const NUMBER_CHAR = '#'

/** A deferred image-blur job: an async closure that blurs its image and writes the result back in place. */
export type BlurJob = () => Promise<void>

/** Per-scrub context: the active allow lists plus tunables read by the scrubbers. */
export interface ScrubContext {
    allow: AllowLists
    /** Optional collector for deferred image-blur jobs (see {@link BlurJob}). */
    blurJobs?: BlurJob[]
}

/** Shared non-null-object type guard used across the scrubbers. */
export function isObject(v: unknown): v is Record<string, any> {
    return typeof v === 'object' && v !== null
}
