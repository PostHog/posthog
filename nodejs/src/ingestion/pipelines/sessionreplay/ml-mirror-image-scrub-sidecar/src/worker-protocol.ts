import { type UndecodableImageReason } from './image-input.ts'
import { type StageTimings } from './scrub.ts'

export interface ScrubJob {
    id: number
    input: Uint8Array
}

export type ScrubFailure =
    | { message: string; kind: 'undecodable'; reason: UndecodableImageReason }
    | { message: string; kind: 'opt-out' | 'failed' }

/** A worker sends `ready` once, then exactly one reply per job. */
export type ScrubReply =
    | { ready: true }
    | { id: number; out: Uint8Array; timings: StageTimings }
    | { id: number; failure: ScrubFailure }
