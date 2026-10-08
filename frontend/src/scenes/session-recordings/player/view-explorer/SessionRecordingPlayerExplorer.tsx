import { useState } from 'react'

import { IconRevert, IconX } from '@posthog/icons'

import { SettingsBar, SettingsButton } from 'lib/components/PanelSettings/PanelSettings'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Timestamp } from 'scenes/session-recordings/player/controller/PlayerControllerTime'
import { ReplaySnapshotFrame } from 'scenes/session-recordings/player/ReplaySnapshotFrame'

export type SessionRecordingPlayerExplorerProps = {
    html: string
    width: number
    height: number
    onClose?: () => void
}

interface PlayerExplorerBottomSettingsProps {
    iframeKey?: any
    setIframeKey?: any
    onClose?: (() => void) | undefined
}

function PlayerExplorerSettings({ iframeKey, setIframeKey, onClose }: PlayerExplorerBottomSettingsProps): JSX.Element {
    return (
        <SettingsBar border="top" className="justify-between">
            <SettingsButton
                data-attr="dom-explorer-reset"
                icon={<IconRevert />}
                onClick={() => setIframeKey(iframeKey + 1)}
                label="Reset"
                title="Reset any changes you've made to the DOM with your developer tools"
            />
            <div className="font-medium flex items-center gap-1.5">
                Snapshot of DOM as it was at <Timestamp size="small" noPadding />
            </div>
            <SettingsButton data-attr="dom-explorer-close" onClick={onClose} label="Close" icon={<IconX />} />
        </SettingsBar>
    )
}

export function SessionRecordingPlayerExplorer({
    html,
    width,
    height,
    onClose,
}: SessionRecordingPlayerExplorerProps): JSX.Element | null {
    const [iframeKey, setIframeKey] = useState(0)
    const [noticeHidden, setNoticeHidden] = useState(false)

    const { ref: elementRef, height: wrapperHeight = height, width: wrapperWidth = width } = useResizeObserver()

    const scale = Math.min(wrapperWidth / width, wrapperHeight / height)

    return (
        <div className="SessionRecordingPlayerExplorer flex flex-1 flex-col h-full overflow-hidden">
            <PlayerExplorerSettings iframeKey={iframeKey} setIframeKey={setIframeKey} onClose={onClose} />
            <div
                className="flex-1 p-0.5 overflow-hidden bg-text-3000 border SessionRecordingPlayerExplorer__wrapper"
                ref={elementRef}
            >
                <ReplaySnapshotFrame
                    key={iframeKey}
                    html={html}
                    title="Session recording DOM explorer"
                    // The app writes the snapshot into this frame, so it must be same-origin. Nothing runs in it.
                    sandbox="allow-same-origin"
                    className="origin-top-left ph-no-capture"
                    style={{ width, height, transform: `scale(${scale})` }}
                />
            </div>
            {!noticeHidden && (
                <LemonBanner square={true} type="info" onClose={() => setNoticeHidden(true)}>
                    This is a snapshot of the screen that was recorded. It may not be 100% accurate, but should be close
                    enough to help you debug.
                    <br />
                    You can interact with the content below but most things won't work as it is only a snapshot of your
                    app. Use your Browser Developer Tools to inspect the content.
                </LemonBanner>
            )}
        </div>
    )
}
