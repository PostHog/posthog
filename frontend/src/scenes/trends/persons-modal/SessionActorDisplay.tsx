import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { humanFriendlyDuration, midEllipsis } from 'lib/utils'
import { asDisplay } from 'scenes/persons/person-utils'
import { gatherIconProperties, PropertyIcons } from 'scenes/session-recordings/playlist/SessionRecordingPreview'

import { SessionActorType } from '~/types'

export function SessionActorDisplay({ actor }: { actor: SessionActorType }): JSX.Element {
    const iconProps = gatherIconProperties(actor.person?.properties)

    return (
        <>
            <div className="flex items-center gap-1 whitespace-nowrap">
                <span className="font-bold">
                    {actor.created_at
                        ? new Date(actor.created_at).toLocaleString(undefined, {
                              month: 'short',
                              day: 'numeric',
                              hour: 'numeric',
                              minute: '2-digit',
                          })
                        : 'Unknown time'}
                </span>
                {actor.properties?.$session_duration != null && (
                    <span className="text-secondary font-normal">
                        · {humanFriendlyDuration(actor.properties.$session_duration)}
                    </span>
                )}
                <span className="text-secondary font-normal">·</span>
                <PropertyIcons recordingProperties={iconProps} loading={false} />
            </div>
            <CopyToClipboardInline
                explicitValue={actor.person ? asDisplay(actor.person) : actor.id}
                iconStyle={{ color: 'var(--color-accent)' }}
                iconPosition="end"
                className="text-xs text-secondary"
            >
                {actor.person ? asDisplay(actor.person) : midEllipsis(actor.id, 32)}
            </CopyToClipboardInline>
        </>
    )
}
