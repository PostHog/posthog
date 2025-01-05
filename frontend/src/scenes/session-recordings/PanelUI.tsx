import './SessionReplay.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { PanelFilters } from './panels/Filters'
import { PanelOverview } from './panels/Overview'
import { PanelPlayback } from './panels/Playback'
import { PanelPlaylist } from './panels/Playlist'
import { PlayerInspector } from './player/inspector/PlayerInspector'

export function PanelsUI(): JSX.Element {
    const workspaceConfig = { overview: false, inspector: true }

    const { activeSessionRecordingId } = useValues(sessionRecordingsPlaylistLogic({ updateSearchParams: true }))

    return (
        <PanelLayout className="SessionReplay__layout">
            <PanelContainer primary={false} className="PanelLayout__secondary flex-col">
                <Panel primary={false}>
                    <PanelFilters />
                </Panel>
                <Panel primary className="PanelLayout__playlist overflow-y-auto flex-1 border w-full">
                    <PanelPlaylist />
                </Panel>
            </PanelContainer>

            <PanelContainer primary className="PanelLayout__primary">
                {workspaceConfig.overview && (
                    <PanelContainer primary={false} className="w-full">
                        <Panel primary className="PanelLayout__overview">
                            <PanelOverview />
                        </Panel>
                    </PanelContainer>
                )}
                <PanelContainer primary className="w-full PanelLayout__main">
                    <Panel primary className="PanelLayout__playback">
                        <PanelPlayback />
                    </Panel>
                    {workspaceConfig.inspector && (
                        <Panel primary={false} className="PanelLayout__inspector flex flex-col">
                            {/*TODO: this only works because we're not using a playerkey yet*/}
                            <PlayerInspector sessionRecordingId={activeSessionRecordingId} />
                        </Panel>
                    )}
                </PanelContainer>
            </PanelContainer>
        </PanelLayout>
    )
}

function PanelLayout(props: Omit<PanelContainerProps, 'primary'>): JSX.Element {
    return <PanelContainer {...props} primary={false} />
}

type PanelContainerProps = {
    children: React.ReactNode
    primary: boolean
    className?: string
}

function PanelContainer({ children, primary, className }: PanelContainerProps): JSX.Element {
    return <div className={clsx('flex flex-wrap gap-2', primary && 'flex-1', className)}>{children}</div>
}

function Panel({
    className,
    primary,
    children,
}: {
    className?: string
    primary: boolean
    collapsed?: boolean
    children: JSX.Element
}): JSX.Element {
    return <div className={clsx(primary && 'flex-1', 'border', className)}>{children}</div>
}
