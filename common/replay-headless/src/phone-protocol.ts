/**
 * Messages between the phone replay player (phone-player.ts, inside a WebView) and the app that hosts it.
 * The app keeps the credentials and fetches the blocks; the page only asks for block ranges and gets their text.
 * Timestamps are epoch milliseconds on the recording's clock.
 */

export interface PhoneSource {
    startTs: number
    endTs: number
}

export type PhoneHostCommand =
    | { type: 'init'; sessionId: string; sources: PhoneSource[]; speed: number; skipInactivity: boolean }
    | { type: 'prepare'; targetTs: number; endTs: number | null; play: boolean }
    /** Moves only the end of the window, so playback goes on from where it is. */
    | { type: 'window'; endTs: number | null }
    | { type: 'seek'; ts: number }
    | { type: 'play' }
    | { type: 'pause' }
    | { type: 'speed'; speed: number }
    | { type: 'skipInactivity'; on: boolean }
    | { type: 'blocks'; requestId: number; text: string; done: boolean }
    | { type: 'blocksFailed'; requestId: number; message: string }

export type PhonePlayerMessage =
    | { type: 'loaded' }
    | { type: 'need'; requestId: number; from: number; to: number }
    | { type: 'status'; status: 'loading' | 'readyToPlay' | 'error'; message?: string }
    | { type: 'time'; ts: number; playing: boolean }
    | { type: 'firstFrame'; ts: number }
    | { type: 'ended' }
    | { type: 'mark'; name: string; at: number; detail?: Record<string, number | string> }
    | { type: 'log'; level: 'error' | 'warn'; message: string }
