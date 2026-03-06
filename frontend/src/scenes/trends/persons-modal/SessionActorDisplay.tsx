import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { humanFriendlyDuration } from 'lib/utils'
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
                {iconProps.length > 0 && (
                    <>
                        <span className="text-secondary font-normal">·</span>
                        <PropertyIcons recordingProperties={iconProps} loading={false} />
                    </>
                )}
            </div>
            {actor.person?.id ? (
                <CopyToClipboardInline
                    explicitValue={asDisplay(actor.person)}
                    iconStyle={{ color: 'var(--color-accent)' }}
                    iconPosition="end"
                    className="text-xs text-secondary"
                >
                    <span>{asDisplay(actor.person)}</span>
                </CopyToClipboardInline>
            ) : (
                <span className="text-xs text-secondary">{asDisplay(actor.person)}</span>
            )}
        </>
    )
}
