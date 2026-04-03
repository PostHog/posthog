import './KioskSetup.scss'

import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlay } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { sessionRecordingsKioskLogic } from './sessionRecordingsKioskLogic'

const DATE_RANGE_OPTIONS = [
    { value: '-1h', label: 'Last hour' },
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
    { value: '-30d', label: 'Last 30 days' },
    { value: '-90d', label: 'Last 90 days' },
]

export function KioskSetup(): JSX.Element {
    const { filters } = useValues(sessionRecordingsKioskLogic)
    const { setFilters, startPlayback } = useActions(sessionRecordingsKioskLogic)

    const [visitedPage, setVisitedPage] = useState(filters.visitedPage || '')
    const [dateFrom, setDateFrom] = useState(filters.dateFrom || '-30d')
    const [minDurationSeconds, setMinDurationSeconds] = useState(filters.minDurationSeconds)

    const handleStart = (): void => {
        setFilters({ visitedPage: visitedPage.trim() || null, dateFrom, minDurationSeconds })
        startPlayback()
    }

    return (
        <div className="KioskSetup">
            <div className="KioskSetup__card">
                <h2>Kiosk mode</h2>
                <p className="KioskSetup__description">
                    Auto-play session recordings on a loop. Optionally filter which recordings to show.
                </p>

                <div className="KioskSetup__field">
                    <label htmlFor="kiosk-visited-page">Pages visited (contains)</label>
                    <LemonInput
                        id="kiosk-visited-page"
                        value={visitedPage}
                        onChange={setVisitedPage}
                        placeholder="e.g. /welcome (leave empty for all)"
                        fullWidth
                        onPressEnter={handleStart}
                        autoFocus
                    />
                </div>

                <div className="KioskSetup__field">
                    <label htmlFor="kiosk-date-range">Date range</label>
                    <LemonSelect
                        id="kiosk-date-range"
                        value={dateFrom}
                        onChange={(value) => setDateFrom(value)}
                        options={DATE_RANGE_OPTIONS}
                        fullWidth
                    />
                </div>

                <div className="KioskSetup__field">
                    <label htmlFor="kiosk-min-duration">Minimum active duration (seconds)</label>
                    <LemonInput
                        id="kiosk-min-duration"
                        type="number"
                        min={0}
                        value={minDurationSeconds}
                        onChange={(val) => setMinDurationSeconds(Number(val) || 0)}
                        fullWidth
                        onPressEnter={handleStart}
                    />
                </div>

                <LemonButton type="primary" fullWidth size="large" icon={<IconPlay />} onClick={handleStart}>
                    Start kiosk
                </LemonButton>
            </div>
        </div>
    )
}
