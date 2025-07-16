import { actions, kea, path } from 'kea'
import { RecordingAnnotationForm } from 'scenes/session-recordings/player/commenting/playerFrameCommentOverlayLogic'

import type { playerCommentModelType } from './playerCommentModelType'

/**
 * used as a message bus for decoupled components to signal that a recording should be commented on
 * the currently active player will listen to this and can enter or exit comment mode in response
 */
export const playerCommentModel = kea<playerCommentModelType>([
    path(['scenes', 'session-recordings', 'player', 'playerCommentModel']),
    actions({
        startCommenting: (annotation: RecordingAnnotationForm | null) => ({ annotation }),
    }),
])
