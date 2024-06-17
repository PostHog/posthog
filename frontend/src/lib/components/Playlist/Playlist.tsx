import clsx from 'clsx'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { useRef, useState } from 'react'
import { Resizer } from '../Resizer/Resizer'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { IconCollapse } from '@posthog/icons'

type PlayListSection = { title: string }

type PlaylistProps = { embedded: boolean; sections: PlayListSection[]; loading: boolean, headerActions: Pick<LemonButtonProps, 'onClick'>[] }

export function Playlist({ embedded, sections, loading, headerActions }: PlaylistProps): JSX.Element {
    const [listCollapsed, setListCollapsed] = useState<boolean>(false)
    const playlistRecordingsListRef = useRef<HTMLDivElement>(null)
    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    return (
        <div
            ref={playlistRef}
            data-attr="session-recordings-playlist"
            className={clsx('SessionRecordingsPlaylist', {
                'SessionRecordingsPlaylist--wide': size !== 'small',
                'SessionRecordingsPlaylist--embedded': embedded,
            })}
        >
            <div
                ref={playlistRecordingsListRef}
                className={clsx(
                    'SessionRecordingsPlaylist__list',
                    listCollapsed && 'SessionRecordingsPlaylist__list--collapsed'
                )}
            >
                {listCollapsed ? (
                    <CollapsedList onClickOpen={() => setListCollapsed(false)} />
                ) : (
                    <List sections={sections} headerActions={headerActions} />
                )}
                <Resizer
                    logicKey="player-recordings-list"
                    placement="right"
                    containerRef={playlistRecordingsListRef}
                    closeThreshold={100}
                    onToggleClosed={(value) => setListCollapsed(value)}
                    onDoubleClick={() => setListCollapsed(!listCollapsed)}
                />
            </div>
            <div className="SessionRecordingsPlaylist__player">
                {!activeSessionRecordingId ? (
                    <div className="mt-20">
                        <EmptyMessage
                            title="No recording selected"
                            description="Please select a recording from the list on the left"
                            buttonText="Learn more about recordings"
                            buttonTo="https://posthog.com/docs/user-guides/recordings"
                        />
                    </div>
                ) : (
                    <SessionRecordingPlayer
                        playerKey={props.logicKey ?? 'playlist'}
                        sessionRecordingId={activeSessionRecordingId}
                        matchingEventsMatchType={matchingEventsMatchType}
                        playlistLogic={logic}
                        noBorder
                        pinned={!!pinnedRecordings.find((x) => x.id === activeSessionRecordingId)}
                        setPinned={
                            props.onPinnedChange
                                ? (pinned) => {
                                      if (!activeSessionRecording?.id) {
                                          return
                                      }
                                      props.onPinnedChange?.(activeSessionRecording, pinned)
                                  }
                                : undefined
                        }
                    />
                )}
            </div>
        </div>
    )
}

const CollapsedList = ({ onClickOpen }: { onClickOpen: () => void }) => (
    <div className="flex items-start h-full bg-bg-light border-r p-1">
        <LemonButton size="small" icon={<IconChevronRight />} onClick={onClickOpen} />
    </div>
)

const List = ({ onClickClose, headerActions, sections }: { onClickClose: () => void,headerActions: any, sections: PlaylistProps['sections'] }): JSX.Element => {
    return <div className="flex flex-col w-full bg-bg-light overflow-hidden border-r h-full">
        <div className="shrink-0 relative flex justify-between items-center p-1 gap-1 whitespace-nowrap border-b">
        <LemonButton
                        size="small"
                        icon={<IconCollapse className="rotate-90" />}
                        onClick={onClickClose}
                    />
            {headerActions.map(action => (

            ))}
        </div>
    </div>
}
