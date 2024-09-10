import './PlayerMeta.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function PlayerPersonMeta(): JSX.Element {
    const { logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson } = useValues(playerMetaLogic(logicProps))

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
                        <PersonDisplay person={sessionPerson} withIcon={true} withDisplay={false} noEllipsis={true} />
                    )}
                </div>
            </div>
        </div>
    )
}
