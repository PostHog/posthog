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
        <LemonSelect<EventMatchScope>
            className="ml-2"
            size="small"
            value={value}
            onChange={(scope) => setFilters({ event_match_scope: scope === 'recording' ? 'recording' : undefined })}
            options={[
                {
                    label: 'in the whole session',
                    value: 'session',
                    labelInMenu: (
                        <ScopeOption
                            title="In the whole session"
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
                            description="Events count from one minute before the recording starts until one minute after it ends"
                        />
                    ),
                },
            ]}
            optionTooltipPlacement="bottom-start"
            dropdownMatchSelectWidth={false}
            data-attr="session-recordings-event-match-scope"
        />
    )
}
