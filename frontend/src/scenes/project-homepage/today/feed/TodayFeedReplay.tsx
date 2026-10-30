import { Suspense, lazy, useState } from 'react'

import { IconPlayFilled } from '@posthog/icons'
import { Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { retryImport } from 'lib/utils/retryImport'

// The player is a large bundle, so it loads only when someone presses play.
const SessionRecordingPlayer = lazy(() =>
    retryImport(() =>
        import('scenes/session-recordings/player/SessionRecordingPlayer').then((m) => ({
            default: m.SessionRecordingPlayer,
        }))
    )
)

export function TodayFeedReplay({
    sessionId,
    page,
    caption,
    to,
    onPlay,
    onOpen,
}: {
    sessionId: string
    page: string | null
    caption: string
    to: string
    onPlay: () => void
    onOpen: () => void
}): JSX.Element {
    const [playing, setPlaying] = useState(false)

    return (
        <div className="flex flex-col gap-1">
            <div className="relative aspect-video overflow-hidden rounded-lg border border-border bg-muted">
                {playing ? (
                    <Suspense fallback={<Skeleton className="size-full" />}>
                        <SessionRecordingPlayer
                            sessionRecordingId={sessionId}
                            playerKey={`today-feed-${sessionId}`}
                            autoPlay
                            noMeta
                            noBorder
                            withSidebar={false}
                        />
                    </Suspense>
                ) : (
                    <button
                        type="button"
                        className="group flex size-full cursor-pointer flex-col justify-between p-3 text-left"
                        onClick={() => {
                            setPlaying(true)
                            onPlay()
                        }}
                        aria-label="Play recording"
                        data-attr="today-feed-replay-play"
                    >
                        <Text size="xs" variant="muted" className="truncate" translate="no">
                            {page ?? 'Recording'}
                        </Text>
                        <span className="absolute inset-0 flex items-center justify-center" aria-hidden>
                            <span className="flex size-14 items-center justify-center rounded-full bg-foreground text-background transition-transform group-hover:scale-105 motion-reduce:transition-none [&_svg]:size-6">
                                <IconPlayFilled />
                            </span>
                        </span>
                        <Text size="xs" weight="medium" className="relative truncate">
                            {caption}
                        </Text>
                    </button>
                )}
            </div>
            <LinkPrimitive
                to={to}
                onClick={onOpen}
                className="self-end text-xs text-muted-foreground hover:text-foreground"
                data-attr="today-feed-replay-open"
            >
                Open the recording
            </LinkPrimitive>
        </div>
    )
}
