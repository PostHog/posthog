import { IconInfo } from '@posthog/icons'
import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { RecordingUniversalFilters } from '~/types'

type EventMatchScope = NonNullable<RecordingUniversalFilters['event_match_scope']>

const WHOLE_SESSION_DESCRIPTION =
    'Events count wherever they happen in the session, including before the recording started or after it ended.'
const ONLY_DURING_RECORDING_DESCRIPTION =
    'Events count only while the recording was capturing, so the matched moment is in the video.'

function ScopeOption({ title, description }: { title: string; description: string }): JSX.Element {
    return (
        <div className="p-1">
            <div className="font-bold">{title}</div>
            <div className="font-normal">{description}</div>
        </div>
    )
}

/** Completes the "Match all filters" sentence: "Match all filters only during recording". */
export function RecordingEventMatchScopeSelect({
    filters,
    setFilters,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element | null {
    const enabled = useFeatureFlag('REPLAY_EVENT_MATCH_SCOPE')
    if (!enabled) {
        return null
    }

    const value: EventMatchScope = filters.event_match_scope ?? 'session'

    return (
        <div className="flex items-center font-medium">
            <LemonSelect<EventMatchScope>
                className="mr-1"
                size="small"
                value={value}
                onChange={(scope) => setFilters({ event_match_scope: scope === 'recording' ? 'recording' : undefined })}
                options={[
                    {
                        label: 'in the whole session',
                        value: 'session',
                        labelInMenu: (
                            <ScopeOption title="In the whole session" description={WHOLE_SESSION_DESCRIPTION} />
                        ),
                    },
                    {
                        label: 'only during recording',
                        value: 'recording',
                        labelInMenu: (
                            <ScopeOption
                                title="Only during recording"
                                description={ONLY_DURING_RECORDING_DESCRIPTION}
                            />
                        ),
                    },
                ]}
                optionTooltipPlacement="bottom-start"
                dropdownMatchSelectWidth={false}
                data-attr="session-recordings-event-match-scope"
            />
            <Tooltip
                title={
                    <div className="space-y-1">
                        <p className="mb-0">
                            <strong>In the whole session:</strong> {WHOLE_SESSION_DESCRIPTION}
                        </p>
                        <p className="mb-0">
                            <strong>Only during recording:</strong> {ONLY_DURING_RECORDING_DESCRIPTION}
                        </p>
                    </div>
                }
            >
                <IconInfo className="text-secondary text-base" />
            </Tooltip>
        </div>
    )
}
