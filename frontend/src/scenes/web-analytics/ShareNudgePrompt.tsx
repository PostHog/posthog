import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconShare, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { shareNudgeLogic } from 'scenes/web-analytics/shareNudgeLogic'

export function ShareNudgePrompt(): JSX.Element | null {
    const { promptVisible, promptSource } = useValues(shareNudgeLogic)
    const { dismissForSession } = useActions(shareNudgeLogic)

    if (!promptVisible) {
        return null
    }

    const handleShare = (): void => {
        void copyToClipboard(window.location.href, 'link to share')
        posthog.capture('web analytics share link copied', { source: promptSource })
        dismissForSession()
    }

    return (
        <div
            className="animate-slide-in-right z-top fixed inset-y-0 right-6 my-auto flex h-fit w-[340px] max-w-[calc(100vw-2rem)] flex-col gap-2 rounded-lg border bg-surface-primary p-4 shadow-lg"
            data-attr="web-analytics-share-nudge-prompt"
        >
            <div className="flex items-start justify-between gap-2">
                <h4 className="m-0 text-base font-semibold">Share this view with a colleague</h4>
                <LemonButton size="xsmall" icon={<IconX />} tooltip="Dismiss" onClick={dismissForSession} />
            </div>
            <p className="m-0 text-sm text-muted">
                Web analytics is better with your team. Send this exact view so they see what you see.
            </p>
            <div className="flex">
                <LemonButton type="primary" icon={<IconShare />} onClick={handleShare}>
                    Copy link
                </LemonButton>
            </div>
        </div>
    )
}
