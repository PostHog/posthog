import { type StageTimings } from './scrub.ts'

export interface ScrubJob {
    id: number
    input: Uint8Array
}

/** A worker sends `ready` once, then exactly one reply per job. */
export type ScrubReply =
    | { ready: true }
    | { id: number; out: Uint8Array; timings: StageTimings }
    | { id: number; failure: { message: string; undecodable: boolean } }
