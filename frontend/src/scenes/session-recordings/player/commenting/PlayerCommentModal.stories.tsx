import { Meta } from '@storybook/react'
import { BindLogic, useActions } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
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

// Opening the overlay is what triggers the org-members load (see playerCommentOverlayLogic),
// so the @-mention autocomplete can resolve teammates. Drive it here so the story exercises
// that path and the mention list is populated when you type `@`.
function CommentingModal(): JSX.Element {
    const { setIsCommenting } = useActions(sessionRecordingPlayerLogic)
    useOnMountEffect(() => setIsCommenting(true))
    return <PlayerCommentModal />
}

export function Default(): JSX.Element {
    return (
        <div className="min-h-80 relative">
            <BindLogic logic={sessionRecordingPlayerLogic} props={{ sessionRecordingId: '23' }}>
                <CommentingModal />
            </BindLogic>
        </div>
    )
}
