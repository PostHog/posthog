import type { LoadFailure } from '../trace/types'

/** Where the loaded turns end on one side: `waiting` has more to read once the read in flight lands. */
export type ConversationEdge = 'more' | 'waiting' | 'loading' | 'failed' | 'end'

/** Whether the turns can show. A failed first page fails them, also when it reloads turns already on screen. */
export type ConversationStatus = 'loading' | 'ready' | LoadFailure
