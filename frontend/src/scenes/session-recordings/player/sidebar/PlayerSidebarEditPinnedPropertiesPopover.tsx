import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPin, IconPinFilled, IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, Link } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { personsLogic } from 'scenes/persons/personsLogic'

import { playerMetaLogic } from '../player-meta/playerMetaLogic'
import { sessionRecordingPinnedPropertiesLogic } from '../player-meta/sessionRecordingPinnedPropertiesLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export type PlayerSidebarEditPinnedPropertiesPopoverProps = {
    distinctId?: string
    personId?: string
    onClose?: () => void
}

export function PlayerSidebarEditPinnedPropertiesPopover(
    props: PlayerSidebarEditPinnedPropertiesPopoverProps
): JSX.Element | null {
    const { loadPerson, loadPersonUUID } = useActions(personsLogic({ syncWithUrl: false }))
    const { person, personLoading } = useValues(personsLogic({ syncWithUrl: false }))
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { propertySearchQuery, filteredPropertiesWithInfo } = useValues(playerMetaLogic(logicProps))
    const { setPropertySearchQuery } = useActions(playerMetaLogic(logicProps))
    const { pinnedProperties } = useValues(sessionRecordingPinnedPropertiesLogic)
    const { togglePropertyPin } = useActions(sessionRecordingPinnedPropertiesLogic)

    useEffect(() => {
        if (props.distinctId) {
            loadPerson(props.distinctId)
        } else if (props.personId) {
            loadPersonUUID(props.personId)
        }
    }, [loadPerson, loadPersonUUID, props.distinctId, props.personId])

    if (!props.distinctId && !props.personId) {
        return null
    }

    if (personLoading) {
        return <Spinner />
    }

    // NOTE: This can happen if the Person was deleted or the events associated with the distinct_id had person processing disabled
    if (!person) {
        return (
            <div className="p-2 max-w-160">
                <h4>No person profile associated with this ID</h4>
                <p>
                    Person profiles allow you to see a detailed view of a Person's user properties, track users across
                    devices, and more. To create person profiles, see{' '}
                    <Link to="https://posthog.com/docs/data/persons#capturing-person-profiles">here.</Link>
                </p>
                <p>To edit pinned overview properties, try via another recording with a different user.</p>
            </div>
        )
    }

    return (
        <div className="flex flex-col overflow-hidden max-h-96 w-[400px]">
            <div className="flex items-center gap-2 px-4 py-3 border-b">
                <IconPinFilled className="text-muted" />
                <h4 className="font-semibold m-0">Pinned properties</h4>
            </div>

            <div className="px-4 py-2 border-b">
                <LemonInput
                    placeholder="Search properties..."
                    value={propertySearchQuery}
                    onChange={setPropertySearchQuery}
                    prefix={<IconSearch />}
                    size="small"
                    fullWidth
                    autoFocus
                />
            </div>

            <ScrollableShadows direction="vertical" className="flex-1">
                <div className="flex flex-col">
                    {filteredPropertiesWithInfo.length === 0 ? (
                        <div className="px-4 py-8 text-center text-muted">
                            {propertySearchQuery.trim() ? 'No properties match your search' : 'No properties available'}
                        </div>
                    ) : (
                        filteredPropertiesWithInfo.map(({ propertyKey, propertyInfo }) => {
                            const isPinned = pinnedProperties.includes(propertyKey)

                            const handleToggle = (): void => {
                                togglePropertyPin(propertyKey)
                            }

                            return (
                                <LemonButton
                                    key={propertyKey}
                                    data-attr={
                                        isPinned ? 'session-overview-unpin-property' : 'session-overview-pin-property'
                                    }
                                    size="small"
                                    fullWidth
                                    className="justify-between"
                                    onClick={handleToggle}
                                    sideIcon={isPinned ? <IconPinFilled /> : <IconPin />}
                                    tooltip={
                                        propertyInfo.label !== propertyInfo.originalKey
                                            ? `Sent as: ${propertyInfo.originalKey}`
                                            : undefined
                                    }
                                >
                                    <span>{propertyInfo.label}</span>
                                </LemonButton>
                            )
                        })
                    )}
                </div>
            </ScrollableShadows>
        </div>
    )
}
