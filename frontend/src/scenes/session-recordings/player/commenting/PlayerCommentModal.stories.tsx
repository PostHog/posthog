import { Meta } from '@storybook/react'
import { BindLogic } from 'kea'

import { PlayerCommentModal } from 'scenes/session-recordings/player/commenting/PlayerFrameCommentOverlay'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

const meta: Meta<typeof PlayerCommentModal> = {
    title: 'Replay/Components/Comment modal',
    component: PlayerCommentModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

export function Default(): JSX.Element {
    return (
        <div className="min-h-80 relative">
            <BindLogic logic={sessionRecordingPlayerLogic} props={{ sessionRecordingId: '23' }}>
                <PlayerCommentModal />
            </BindLogic>
        </div>
    )
}
