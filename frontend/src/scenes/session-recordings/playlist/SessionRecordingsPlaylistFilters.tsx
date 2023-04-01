import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconFilter, IconWithCount } from 'lib/lemon-ui/icons'
import { FEATURE_FLAGS } from 'lib/constants'
import { AddToNotebook } from 'scenes/notebooks/AddToNotebook/AddToNotebook'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { eventUsageLogic, SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { DurationFilter } from 'scenes/session-recordings/filters/DurationFilter'
import { RecordingDurationFilter } from '~/types'
import { useAsyncHandler } from 'lib/hooks/useAsyncHandler'
import { createPlaylist } from 'scenes/session-recordings/playlist/playlistUtils'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { SessionRecordingsPlaylistProps } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import clsx from 'clsx'
import { SessionRecordingsFilters } from 'scenes/session-recordings/filters/SessionRecordingsFilters'

export function SessionRecordingsPlaylistFilters({
    playlistShortId,
    personUUID,
    filters: defaultFilters,
    updateSearchParams,
    embedded = false,
}: SessionRecordingsPlaylistProps): JSX.Element {
    const logicProps = {
        playlistShortId,
        personUUID,
        filters: defaultFilters,
        updateSearchParams,
    }
    const logic = sessionRecordingsListLogic(logicProps)
    const { filters, totalFiltersCount, showFilters } = useValues(logic)
    const { setFilters, reportRecordingsListFilterAdded, setShowFilters } = useActions(logic)
    const { reportRecordingPlaylistCreated } = useActions(eventUsageLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const newPlaylistHandler = useAsyncHandler(async () => {
        await createPlaylist({ filters }, true)
        reportRecordingPlaylistCreated('filters')
    })

    const dateFilter = (
        <DateFilter
            dateFrom={filters.date_from ?? '-7d'}
            dateTo={filters.date_to ?? undefined}
            onChange={(changedDateFrom, changedDateTo) => {
                reportRecordingsListFilterAdded(SessionRecordingFilterType.DateRange)
                setFilters({
                    date_from: changedDateFrom,
                    date_to: changedDateTo,
                })
            }}
            dateOptions={[
                { key: 'Custom', values: [] },
                { key: 'Last 24 hours', values: ['-24h'] },
                { key: 'Last 7 days', values: ['-7d'] },
                { key: 'Last 21 days', values: ['-21d'] },
            ]}
        />
    )

    const durationFilter = (
        <DurationFilter
            onChange={(newFilter) => {
                reportRecordingsListFilterAdded(SessionRecordingFilterType.Duration)
                setFilters({ session_recording_duration: newFilter })
            }}
            initialFilter={filters.session_recording_duration as RecordingDurationFilter}
            pageKey={!!personUUID ? `person-${personUUID}` : 'session-recordings'}
        />
    )

    if (embedded) {
        return (
            <div className="flex flex-col gap-4 p-2">
                <SessionRecordingsFilters filters={filters} setFilters={setFilters} showPropertyFilters={!personUUID} />
                <div className="flex flex-col gap-1">
                    <LemonLabel>Date</LemonLabel>
                    {dateFilter}
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Duration</LemonLabel>
                    {durationFilter}
                </div>
            </div>
        )
    }

    return (
        <div className={clsx('flex flex-wrap items-end justify-between gap-4 mb-4')}>
            <div className="flex items-center gap-4">
                <>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={
                            <IconWithCount count={totalFiltersCount}>
                                <IconFilter />
                            </IconWithCount>
                        }
                        onClick={() => {
                            setShowFilters(!showFilters)
                            if (personUUID) {
                                const entityFilterButtons = document.querySelectorAll('.entity-filter-row button')
                                if (entityFilterButtons.length > 0) {
                                    ;(entityFilterButtons[0] as HTMLElement).click()
                                }
                            }
                        }}
                    >
                        {showFilters ? 'Hide filters' : 'Filters'}
                    </LemonButton>

                    {!playlistShortId ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={newPlaylistHandler.onEvent}
                            loading={newPlaylistHandler.loading}
                            data-attr="save-recordings-playlist-button"
                        >
                            Save as playlist
                        </LemonButton>
                    ) : null}
                    {!!featureFlags[FEATURE_FLAGS.NOTEBOOKS] ? (
                        <AddToNotebook
                            type="secondary"
                            icon={null}
                            node={NotebookNodeType.RecordingPlaylist}
                            properties={{ filters: {} }}
                            data-attr="add-playlist-to-notebook-button"
                        >
                            Add to notebook
                        </AddToNotebook>
                    ) : null}
                </>
            </div>

            <div className="flex items-center gap-4">
                {dateFilter}
                <div className="flex gap-2">
                    <LemonLabel>Duration</LemonLabel>
                    {durationFilter}
                </div>
            </div>
        </div>
    )
}
