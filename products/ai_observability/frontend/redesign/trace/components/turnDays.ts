import { dayjs } from 'lib/dayjs'

import { ConversationTurn } from '../types'

/** Whether the turn opens a calendar day in the viewer's timezone: the first turn shown, or the first of a later day. */
export function startsDay(previous: ConversationTurn | null, turn: ConversationTurn): boolean {
    return previous === null || !dayjs(previous.timestamp).isSame(dayjs(turn.timestamp), 'day')
}
