import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconShare, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { shareNudgeLogic } from 'scenes/web-analytics/shareNudgeLogic'

export function ShareNudgePrompt(): JSX.Element | null {
    const { promptVisible, promptAnchor } = useValues(shareNudgeLogic)
    const { dismissForSession } = useActions(shareNudgeLogic)

    if (!promptVisible || !promptAnchor) {
        return null
    }

    const left = Math.min(promptAnchor.x, window.innerWidth - 300)
    const top = Math.min(promptAnchor.y + 8, window.innerHeight - 120)

    const handleShare = (): void => {
        void copyToClipboard(window.location.href, 'link to share')
        posthog.capture('web analytics share link copied', { source: 'intent_prompt' })
        dismissForSession()
    }

    return (
        <div
            className="z-top fixed flex items-center gap-2 rounded border bg-surface-primary p-2 shadow-md"
            style={{ left, top, maxWidth: 280 }}
            data-attr="web-analytics-share-nudge-prompt"
        >
            <span className="text-sm">Share this with a colleague?</span>
            <LemonButton type="primary" size="xsmall" icon={<IconShare />} onClick={handleShare}>
                Copy link
            </LemonButton>
            <LemonButton size="xsmall" icon={<IconX />} tooltip="Dismiss" onClick={dismissForSession} />
        </div>
    )
}
