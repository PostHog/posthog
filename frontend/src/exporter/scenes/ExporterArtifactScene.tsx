import { useState } from 'react'

import { IconDownload } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanizeBytes } from 'lib/utils/numbers'

import { SharedTaskArtifactPayload } from '../types'

function DownloadCard({ artifact }: { artifact: SharedTaskArtifactPayload }): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-2">
            {/* A real navigation: the file streams from the server, so client-side routing must stay out of it. */}
            <LemonButton
                type="primary"
                icon={<IconDownload />}
                to={`${artifact.file_url}?download=true`}
                disableClientSideRouting
            >
                Download {artifact.name}
            </LemonButton>
            {artifact.size !== null && <span className="text-muted text-xs">{humanizeBytes(artifact.size)}</span>}
            {artifact.kind === 'html' && (
                <span className="text-muted text-xs">
                    HTML files download instead of opening here, so the page stays safe to visit.
                </span>
            )}
        </div>
    )
}

export default function ExporterArtifactScene({ artifact }: { artifact: SharedTaskArtifactPayload }): JSX.Element {
    if (artifact.kind === 'markdown') {
        if (artifact.markdown === null) {
            return (
                <div className="flex flex-col gap-4">
                    <LemonBanner type="info">This file is too large to show here. Download it to read it.</LemonBanner>
                    <DownloadCard artifact={artifact} />
                </div>
            )
        }
        return (
            <div className="max-w-3xl mx-auto w-full">
                {/* An agent wrote this file, and the page is public: a remote image would report
                    every anonymous viewer back to whoever the URL points at. */}
                <LemonMarkdown disableImages>{artifact.markdown}</LemonMarkdown>
            </div>
        )
    }
    if (artifact.kind === 'image') {
        return <SharedImage artifact={artifact} />
    }
    return <DownloadCard artifact={artifact} />
}

/** The page renders before the image endpoint reads storage, so a gone or unreadable
 * object has to say so instead of leaving a broken-image icon. */
function SharedImage({ artifact }: { artifact: SharedTaskArtifactPayload }): JSX.Element {
    const [failed, setFailed] = useState(false)

    if (failed) {
        return (
            <div className="flex flex-col gap-4">
                <LemonBanner type="warning">
                    This image couldn't be loaded. It may no longer be available. Try again, or ask whoever shared it
                    for a new link.
                </LemonBanner>
                <DownloadCard artifact={artifact} />
            </div>
        )
    }

    return (
        <div className="flex justify-center">
            <img
                src={artifact.file_url}
                alt={artifact.name}
                className="max-w-full h-auto"
                onError={() => setFailed(true)}
            />
        </div>
    )
}
