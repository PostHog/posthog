import './SessionReplay.scss'

import clsx from 'clsx'
import { BindLogic } from 'kea'

import { PanelPlayback } from './panels/Playback'
import { PanelPlaylist } from './panels/Playlist'
import {
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from './playlist/sessionRecordingsPlaylistLogic'
import { PlayerSidebar } from './player/PlayerSidebar'

export function PanelsUI(props: SessionRecordingPlaylistLogicProps): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        ...props,
        autoPlay: props.autoPlay ?? true,
    }

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <PanelLayout className="SessionReplay__layout">
                <PanelContainer primary={false} className="PanelLayout__secondary flex-col">
                    <Panel primary={false} className="bg-[red]">
                        <>Filters</>
                    </Panel>
                    <Panel primary className="PanelLayout__playlist bg-[yellow]">
                        <PanelPlaylist isCollapsed={false} />
                    </Panel>
                </PanelContainer>

                <PanelContainer primary className="PanelLayout__primary">
                    <Panel primary className="PanelLayout__playback bg-[green]">
                        <PanelPlayback logicKey={props.logicKey} />
                    </Panel>
                    <Panel primary={false} className="PanelLayout__inspector bg-[pink]">
                        <PlayerSidebar />
                    </Panel>
                </PanelContainer>
            </PanelLayout>
        </BindLogic>
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
    children: JSX.Element
}): JSX.Element {
    return <div className={clsx(className, primary && 'flex-1', 'border')}>{children}</div>
}
