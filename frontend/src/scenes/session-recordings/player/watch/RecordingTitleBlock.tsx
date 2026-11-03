import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Button, Heading, Skeleton } from '@posthog/quill'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { PlayerMetaExperimentTags } from 'scenes/session-recordings/player/player-meta/PlayerMetaExperimentTags'
import { PinToPlaylistButton } from 'scenes/session-recordings/player/player-meta/PlayerMetaLinks'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { gatherIconProperties } from 'scenes/session-recordings/playlist/gatherIconProperties'
import { sessionRecordingsListPropertiesLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListPropertiesLogic'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { PersonIcon } from 'products/persons/frontend/components/PersonDisplay'
import { asDisplay, asLink } from 'products/persons/frontend/person-utils'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function RecordingTitleBlock({ actions }: { actions?: ReactNode }): JSX.Element {
    const { logicProps, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson, loading, startTime } = useValues(playerMetaLogic(logicProps))
    const { recordingPropertiesById } = useValues(sessionRecordingsListPropertiesLogic)
    // The playlist host binds this logic, so the filter lands on the list beside the player.
    const { filterByPerson } = useActions(sessionRecordingsPlaylistLogic)
    const { setPlaylistCollapsed } = useActions(playerSettingsLogic)

    const actionBar = (
        <div className="ml-auto flex items-center gap-2 flex-wrap" data-attr="watch-panel-title-actions">
            {actions}
            <PinToPlaylistButton size="small" type="secondary" labelled />
        </div>
    )

    if (loading) {
        return (
            <div data-quill className="flex items-center gap-3">
                <Skeleton className="w-10 h-10 rounded-full" />
                <div className="flex flex-col gap-1 flex-1">
                    <Skeleton className="w-1/3 h-5" />
                    <Skeleton className="w-1/2 h-4" />
                </div>
                {actionBar}
            </div>
        )
    }

    const recordingProperties = sessionPlayerMetaData?.id
        ? recordingPropertiesById[sessionPlayerMetaData.id]
        : undefined
    const iconProperties = gatherIconProperties(recordingProperties, sessionPlayerMetaData ?? undefined)
    const durationSeconds = sessionPlayerMetaData?.recording_duration
    const personName = sessionPerson ? asDisplay(sessionPerson) : 'Unknown user'
    const personHref = asLink(sessionPerson)
    const personUUID = sessionPerson?.uuid
    const showMoreFromPerson = (): void => {
        if (personUUID) {
            filterByPerson(personUUID)
            setPlaylistCollapsed(false)
        }
    }

    return (
        <div
            data-quill
            className="flex items-start gap-3 min-w-0 flex-wrap text-foreground"
            data-attr="watch-panel-title"
        >
            {sessionPerson && <PersonIcon person={sessionPerson} size="lg" className="mr-0 shrink-0" />}
            <div className="flex flex-col gap-0.5 min-w-0 flex-1 basis-72">
                <Heading size="base" render={<h2 />} className="truncate m-0 ph-no-capture">
                    {personHref ? (
                        <Button
                            variant="link-muted"
                            size="inline"
                            render={<LinkPrimitive to={personHref} />}
                            data-attr="watch-panel-title-person"
                        >
                            {personName}
                        </Button>
                    ) : (
                        personName
                    )}
                </Heading>
                {personUUID && (
                    <div>
                        <Button
                            onClick={showMoreFromPerson}
                            tooltip="Filter the list to this person's recordings"
                            className="-ml-1"
                            data-attr="watch-panel-more-from-person"
                        >
                            More from this person
                            <IconChevronRight />
                        </Button>
                    </div>
                )}
                <div className="flex items-center gap-x-2 gap-y-0.5 flex-wrap text-xs text-muted-foreground ph-no-capture">
                    {durationSeconds !== undefined && <span>{humanFriendlyDuration(durationSeconds)}</span>}
                    {startTime && <TZLabel time={startTime} showPopover={false} />}
                    {iconProperties.map(({ property, value, label }) => (
                        <span key={property} className="flex items-center gap-x-1">
                            <PropertyIcon property={property} value={value} />
                            <span>{label}</span>
                        </span>
                    ))}
                    <PlayerMetaExperimentTags />
                </div>
            </div>
            {actionBar}
        </div>
    )
}
