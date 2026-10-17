import pLimit from 'p-limit'
import { Counter } from 'prom-client'

import type { TeamDayKey, TeamDayKeys } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-day-keys'
import type { FetchCandidate } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/collected-urls-record'
import { parseV4UrlRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

const DAY_MS = 24 * 60 * 60 * 1000
/** Each lookup's read budget starts when it starts, so a batch of many new team days must not start them all at once. */
const KEY_LOOKUP_CONCURRENCY = 16

const droppedJobs = new Counter({
    name: 'ai_research_image_fetch_v4_dropped_jobs_total',
    help: 'v4 fetch jobs dropped before any request, by reason.',
    labelNames: ['reason'],
})

/**
 * Drops a v4 job before any request when nothing could store its image: its day is past the raw window, or its team
 * day has no key row or a tombstone. The recorder stores the row before it sends a URL, so a missing row means it expired.
 */
export class V4JobAdmission {
    private readonly keyLookups = pLimit(KEY_LOOKUP_CONCURRENCY)

    constructor(
        private readonly keys: Pick<TeamDayKeys, 'get'>,
        private readonly maxRefAgeDays: number
    ) {
        if (!Number.isSafeInteger(maxRefAgeDays) || maxRefAgeDays < 0) {
            throw new Error(
                `AI_RESEARCH_REPLAY_V4_IMAGE_FETCH_MAX_REF_AGE_DAYS must be a whole number, got ${maxRefAgeDays}`
            )
        }
    }

    public async admit(candidates: FetchCandidate[], nowMs: number): Promise<FetchCandidate[]> {
        const keys = new Map<string, Promise<TeamDayKey>>()
        const inWindow: { candidate: FetchCandidate; teamDay: string }[] = []
        for (const candidate of candidates) {
            const ref = parseV4UrlRef(candidate.originalRef)
            if (!ref) {
                droppedJobs.labels('foreign_ref').inc()
                continue
            }
            if (Math.floor((nowMs - Date.parse(`${ref.keyDay}T00:00:00Z`)) / DAY_MS) > this.maxRefAgeDays) {
                droppedJobs.labels('expired').inc()
                continue
            }
            const teamDay = `${ref.teamId}:${ref.keyDay}`
            if (!keys.has(teamDay)) {
                keys.set(
                    teamDay,
                    this.keyLookups(() => this.keys.get(ref.teamId, ref.keyDay))
                )
            }
            inWindow.push({ candidate, teamDay })
        }
        const resolved = new Map(
            await Promise.all([...keys].map(async ([teamDay, key]) => [teamDay, await key] as const))
        )
        const admitted: FetchCandidate[] = []
        for (const { candidate, teamDay } of inWindow) {
            const key = resolved.get(teamDay)!
            if (key.status === 'ok') {
                admitted.push(candidate)
            } else {
                droppedJobs.labels(key.status === 'deleted' ? 'deleted' : 'missing_key').inc()
            }
        }
        return admitted
    }
}
