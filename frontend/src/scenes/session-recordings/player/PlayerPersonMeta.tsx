import './PlayerMeta.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function PlayerPersonMeta(): JSX.Element {
    const { logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson, startTime } = useValues(playerMetaLogic(logicProps))

    return (
        <div
            className={clsx('PlayerMeta', {
                'PlayerMeta--fullscreen': isFullScreen,
            })}
        >
            <div className={clsx('PlayerMeta__top flex items-center gap-1 shrink-0', isFullScreen && ' text-xs')}>
                <div className="ph-no-capture">
                    {!sessionPerson ? (
                        <LemonSkeleton.Circle className="w-8 h-8" />
                    ) : (
                        <ProfilePicture size="md" name={asDisplay(sessionPerson)} />
                    )}
                </div>
                <div className="overflow-hidden ph-no-capture flex-1">
                    <div>
                        {!sessionPerson || !startTime ? (
                            <LemonSkeleton className="w-1/3 h-4 my-1" />
                        ) : (
                            <div className="flex gap-1">
                                <span className="font-bold whitespace-nowrap truncate">
                                    <PersonDisplay person={sessionPerson} withIcon={false} noEllipsis={true} />
                                </span>
                                ·
                                <TZLabel
                                    time={dayjs(startTime)}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="h:mm A"
                                    showPopover={false}
                                />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
