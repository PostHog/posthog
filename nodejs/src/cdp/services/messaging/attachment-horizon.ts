import { ATTACHMENT_LIFETIME_MS, DAY_MS } from './attachment-store'

export const SEND_NEEDS_FILES_FOR_MS = 7 * DAY_MS
export const LONGEST_WAIT_FOR_ROOM_MS = SEND_NEEDS_FILES_FOR_MS - DAY_MS

const STORE_CLOCK_MARGIN_MS = 60 * 1000

export const sendNeedsFilesUntil = (dueAt: Date | undefined, now = Date.now()): Date =>
    new Date(
        Math.min(
            (dueAt?.getTime() ?? now) + SEND_NEEDS_FILES_FOR_MS,
            now + ATTACHMENT_LIFETIME_MS - STORE_CLOCK_MARGIN_MS
        )
    )
