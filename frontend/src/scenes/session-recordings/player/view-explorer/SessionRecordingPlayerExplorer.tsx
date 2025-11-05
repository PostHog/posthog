import { useState } from 'react'

import { IconRevert, IconX } from '@posthog/icons'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SettingsBar, SettingsButton } from 'scenes/session-recordings/components/PanelSettings'
import { Timestamp } from 'scenes/session-recordings/player/controller/PlayerControllerTime'

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
                icon={<IconRevert />}
                onClick={() => setIframeKey(iframeKey + 1)}
                label="Reset"
                title="Reset any changes you've made to the DOM with your developer tools"
            />
            <div className="font-medium">
                Snapshot of DOM as it was at <Timestamp size="small" noPadding />
            </div>
            <SettingsButton onClick={onClose} label="Close" icon={<IconX />} />
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
                <iframe
                    key={iframeKey}
                    srcDoc={html}
                    width={width}
                    height={height}
                    className="origin-top-left ph-no-capture"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ transform: `scale(${scale})` }}
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
