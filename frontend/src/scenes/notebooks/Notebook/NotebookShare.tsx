import { LemonBanner, LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { IconCopy } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { base64Encode } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import posthog from 'posthog-js'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { notebookLogic } from './notebookLogic'

export type NotebookShareProps = {
    shortId: string
}
export function NotebookShare({ shortId }: NotebookShareProps): JSX.Element {
    const { content, isLocalOnly } = useValues(notebookLogic({ shortId }))
    const url = combineUrl(`${window.location.origin}${urls.notebook(shortId)}`).url

    const canvasUrl =
        combineUrl(`${window.location.origin}${urls.canvas()}`).url + `#🦔=${base64Encode(JSON.stringify(content))}`

    const [interestTracked, setInterestTracked] = useState(false)

    const trackInterest = (): void => {
        posthog.capture('pressed interested in notebook sharing', { url })
    }

    return (
        <div className="space-y-2">
            <h3>Internal Link</h3>
            {!isLocalOnly ? (
                <>
                    <p>
                        <b>Click the button below</b> to copy a direct link to this Notebook. Make sure the person you
                        share it with has access to this PostHog project.
                    </p>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        center
                        sideIcon={<IconCopy />}
                        onClick={() => void copyToClipboard(url, 'notebook link')}
                        title={url}
                    >
                        <span className="truncate">{url}</span>
                    </LemonButton>

                    <LemonDivider className="my-4" />
                </>
            ) : (
                <LemonBanner type="info">
                    <p>This Notebook cannot be shared directly with others as it is only visible to you.</p>
                </LemonBanner>
            )}

            <h3>Template Link</h3>
            <p>
                The link below will open a Canvas with the contents of this Notebook, allowing the receiver to view it,
                edit it or create their own Notebook without affecting this one.
            </p>
            <LemonButton
                type="secondary"
                fullWidth
                center
                sideIcon={<IconCopy />}
                onClick={() => void copyToClipboard(canvasUrl, 'canvas link')}
                title={url}
            >
                <span className="truncate">{canvasUrl}</span>
            </LemonButton>

            <LemonDivider className="my-4" />

            <h3>External Sharing</h3>

            <LemonBanner
                type="warning"
                action={{
                    children: !interestTracked ? 'I would like this!' : 'Thanks!',
                    onClick: () => {
                        if (!interestTracked) {
                            trackInterest()
                            setInterestTracked(true)
                        }
                    },
                }}
            >
                We don’t currently support sharing notebooks externally, but it’s on our roadmap!
            </LemonBanner>
        </div>
    )
}

export function openNotebookShareDialog({ shortId }: NotebookShareProps): void {
    LemonDialog.open({
        title: 'Share notebook',
        content: <NotebookShare shortId={shortId} />,
        width: 600,
        primaryButton: {
            children: 'Close',
            type: 'secondary',
        },
    })
}
