import { DAY_MS } from './attachment-store'

export const SEND_NEEDS_FILES_FOR_MS = 7 * DAY_MS
export const LONGEST_WAIT_FOR_ROOM_MS = SEND_NEEDS_FILES_FOR_MS - DAY_MS
