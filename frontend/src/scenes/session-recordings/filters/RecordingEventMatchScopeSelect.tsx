import { LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { RecordingUniversalFilters } from '~/types'

type EventMatchScope = NonNullable<RecordingUniversalFilters['event_match_scope']>

function ScopeOption({ title, description }: { title: string; description: string }): JSX.Element {
    return (
        <div className="p-1">
            <div className="font-bold">{title}</div>
            <div className="font-normal">{description}</div>
        </div>
    )
}

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
            <span className="ml-2">Match</span>
            <LemonSelect<EventMatchScope>
                className="mx-2"
                size="small"
                value={value}
                onChange={(scope) => setFilters({ event_match_scope: scope === 'recording' ? 'recording' : undefined })}
                options={[
                    {
                        label: 'the whole session',
                        value: 'session',
                        labelInMenu: (
                            <ScopeOption
                                title="The whole session"
                                description="Events count wherever they happen in the session, including before the recording started or after it ended"
                            />
                        ),
                    },
                    {
                        label: 'only during recording',
                        value: 'recording',
                        labelInMenu: (
                            <ScopeOption
                                title="Only during recording"
                                description="Events count only while the recording was capturing, so the matched moment is in the video"
                            />
                        ),
                    },
                ]}
                optionTooltipPlacement="bottom-start"
                dropdownMatchSelectWidth={false}
                data-attr="session-recordings-event-match-scope"
            />
        </div>
    )
}
