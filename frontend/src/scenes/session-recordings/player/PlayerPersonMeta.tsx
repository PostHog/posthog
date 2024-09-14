import './PlayerMeta.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PersonDisplay, PersonIcon } from 'scenes/persons/PersonDisplay'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function PlayerPersonMeta(): JSX.Element {
    const { logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson } = useValues(playerMetaLogic(logicProps))

    return (
        <div
            className={clsx('PlayerMeta mb-2', {
                'PlayerMeta--fullscreen': isFullScreen,
            })}
        >
            <div className={clsx('PlayerMeta__top flex items-center gap-1 shrink-0', isFullScreen && ' text-xs')}>
                <div className="ph-no-capture">
                    {!sessionPerson ? (
                        <LemonSkeleton.Circle className="w-8 h-8" />
                    ) : (
                        <PersonDisplay person={sessionPerson}>
                            <PersonIcon person={sessionPerson} size="md" className="mr-0" />
                        </PersonDisplay>
                    )}
                </div>
            </div>
        </div>
    )
}
