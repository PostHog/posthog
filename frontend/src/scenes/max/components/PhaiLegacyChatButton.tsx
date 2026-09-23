import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'

export function PhaiLegacyChatButton({ draft, panelId }: { draft: string; panelId: string }): JSX.Element {
    const { setPhaiViewMode } = useActions(maxGlobalLogic)
    const { startNewConversation, setQuestion } = useActions(maxLogic({ panelId }))

    return (
        <LemonButton
            type="primary"
            size="small"
            className="mt-2"
            data-attr="phai-access-fallback"
            onClick={() => {
                startNewConversation()
                setQuestion(draft)
                setPhaiViewMode('legacy')
            }}
        >
            Use legacy PostHog AI
        </LemonButton>
    )
}
