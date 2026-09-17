import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { teamLogic } from 'scenes/teamLogic'

const DEFAULT_LOOKBACK_MINUTES = 180
const DEFAULT_MIN_TICKETS = 3
const DEFAULT_MIN_REQUESTERS = 3

// Kept in step with the ranges TeamSerializer.validate_conversations_settings rejects outside of.
const MIN_COUNT = 2
const MAX_COUNT = 50

const WINDOW_OPTIONS = [
    { value: 60, label: '1 hour' },
    { value: 180, label: '3 hours' },
    { value: 360, label: '6 hours' },
    { value: 720, label: '12 hours' },
    { value: 1440, label: '24 hours' },
]

// A cleared number input reports NaN, which must save as null to restore the default.
function toInputValue(count: number | null | undefined): number | null {
    return typeof count === 'number' && Number.isFinite(count) ? count : null
}

function errorFor(count: number | null): string | undefined {
    if (count === null) {
        return undefined
    }
    if (!Number.isInteger(count)) {
        return 'Enter a whole number'
    }
    if (count < MIN_COUNT || count > MAX_COUNT) {
        return `Enter a number from ${MIN_COUNT} to ${MAX_COUNT}`
    }
    return undefined
}

export function TicketPatternThresholds(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const settings = currentTeam?.conversations_settings
    const savedWindow = settings?.ticket_patterns_lookback_minutes ?? DEFAULT_LOOKBACK_MINUTES
    const savedMinTickets = toInputValue(settings?.ticket_patterns_min_tickets)
    const savedMinRequesters = toInputValue(settings?.ticket_patterns_min_requesters)

    const [lookbackMinutes, setLookbackMinutes] = useState<number>(savedWindow)
    const [minTickets, setMinTickets] = useState<number | null>(savedMinTickets)
    const [minRequesters, setMinRequesters] = useState<number | null>(savedMinRequesters)

    useEffect(() => {
        setLookbackMinutes(savedWindow)
        setMinTickets(savedMinTickets)
        setMinRequesters(savedMinRequesters)
    }, [savedWindow, savedMinTickets, savedMinRequesters])

    const minTicketsError = errorFor(minTickets)
    const minRequestersError = errorFor(minRequesters)
    const unchanged =
        lookbackMinutes === savedWindow && minTickets === savedMinTickets && minRequesters === savedMinRequesters

    // A window the team already has stays selectable, so saving the other two fields cannot
    // silently move it onto a preset.
    const windowOptions = WINDOW_OPTIONS.some((option) => option.value === savedWindow)
        ? WINDOW_OPTIONS
        : [...WINDOW_OPTIONS, { value: savedWindow, label: `${savedWindow} minutes` }]

    return (
        <div className="@container">
            <div className="flex flex-wrap gap-4">
                <LemonField.Pure
                    className="flex-1 min-w-40"
                    label="Time window"
                    htmlFor="ticket-patterns-window"
                    help="How far back each check looks."
                >
                    <LemonSelect<number>
                        id="ticket-patterns-window"
                        value={lookbackMinutes}
                        options={windowOptions}
                        onChange={(value) => setLookbackMinutes(value ?? DEFAULT_LOOKBACK_MINUTES)}
                        data-attr="ticket-patterns-window"
                    />
                </LemonField.Pure>
                <LemonField.Pure
                    className="flex-1 min-w-40"
                    label="Minimum tickets"
                    htmlFor="ticket-patterns-min-tickets"
                    help={`Leave empty to use the default of ${DEFAULT_MIN_TICKETS}.`}
                    error={minTicketsError}
                >
                    <LemonInput
                        id="ticket-patterns-min-tickets"
                        type="number"
                        min={MIN_COUNT}
                        max={MAX_COUNT}
                        value={minTickets ?? undefined}
                        onChange={(value) => setMinTickets(toInputValue(value))}
                        placeholder={`${DEFAULT_MIN_TICKETS}`}
                        data-attr="ticket-patterns-min-tickets"
                    />
                </LemonField.Pure>
                <LemonField.Pure
                    className="flex-1 min-w-40"
                    label="Minimum customers"
                    htmlFor="ticket-patterns-min-requesters"
                    help={`Leave empty to use the default of ${DEFAULT_MIN_REQUESTERS}. Counting customers rather than tickets keeps one busy sender from looking like a spike.`}
                    error={minRequestersError}
                >
                    <LemonInput
                        id="ticket-patterns-min-requesters"
                        type="number"
                        min={MIN_COUNT}
                        max={MAX_COUNT}
                        value={minRequesters ?? undefined}
                        onChange={(value) => setMinRequesters(toInputValue(value))}
                        placeholder={`${DEFAULT_MIN_REQUESTERS}`}
                        data-attr="ticket-patterns-min-requesters"
                    />
                </LemonField.Pure>
            </div>
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    loading={currentTeamLoading}
                    onClick={() =>
                        updateCurrentTeam({
                            conversations_settings: {
                                ...currentTeam?.conversations_settings,
                                ticket_patterns_lookback_minutes: lookbackMinutes,
                                ticket_patterns_min_tickets: minTickets,
                                ticket_patterns_min_requesters: minRequesters,
                            },
                        })
                    }
                    disabledReason={
                        minTicketsError || minRequestersError
                            ? 'Fix the thresholds above to save'
                            : unchanged
                              ? 'No changes to save'
                              : currentTeamLoading
                                ? 'Saving'
                                : undefined
                    }
                    data-attr="ticket-patterns-thresholds-save"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
