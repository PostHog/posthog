import { actions, kea, path } from 'kea'

import { RecordingCommentForm } from 'scenes/session-recordings/player/commenting/playerFrameCommentOverlayLogic'

import type { playerCommentModelType } from './playerCommentModelType'

/**
 * used as a message bus for decoupled components to signal that a recording should be commented on
 * the currently active player will listen to this
 * and can e.g. enter or exit comment mode in response
 * it relies on being used when there is always a mounted player with a logic listening for this
 */
export const playerCommentModel = kea<playerCommentModelType>([
    path(['scenes', 'session-recordings', 'player', 'playerCommentModel']),
    actions({
        startCommenting: (comment: RecordingCommentForm | null) => ({ comment }),
        commentEdited: (recordingId: string) => ({ recordingId }),
    }),
])
