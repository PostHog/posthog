import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { errorTrackingDataLogic } from './errorTrackingDataLogic'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const ErrorTrackingActions = ({ showOrder = true }: { showOrder?: boolean }): JSX.Element => {
    const { dateRange } = useValues(errorTrackingLogic)
    const { setDateRange } = useActions(errorTrackingLogic)
    const { order, selectedRows } = useValues(errorTrackingSceneLogic)
    const { setOrder, setSelectedRows } = useActions(errorTrackingSceneLogic)
    const { mergeGroups } = useActions(errorTrackingDataLogic)

    return selectedRows.length === 0 ? (
        <div className="flex gap-4">
            <div className="flex items-center gap-1">
                <span>Date range:</span>
                <DateFilter
                    dateFrom={dateRange.date_from}
                    dateTo={dateRange.date_to}
                    onChange={(changedDateFrom, changedDateTo) => {
                        setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                    }}
                    size="small"
                />
            </div>
            {showOrder && (
                <div className="flex items-center gap-1">
                    <span>Sort by:</span>
                    <LemonSelect
                        onSelect={setOrder}
                        onChange={setOrder}
                        value={order}
                        options={[
                            {
                                value: 'last_seen',
                                label: 'Last seen',
                            },
                            {
                                value: 'first_seen',
                                label: 'First seen',
                            },
                            {
                                value: 'occurrences',
                                label: 'Occurrences',
                            },
                            {
                                value: 'users',
                                label: 'Users',
                            },
                            {
                                value: 'sessions',
                                label: 'Sessions',
                            },
                        ]}
                        size="small"
                    />
                </div>
            )}
        </div>
    ) : (
        <div className="flex space-x-1">
            <LemonButton type="secondary" size="small" onClick={() => setSelectedRows([])}>
                Unselect all
            </LemonButton>
            {selectedRows.length > 1 && (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => {
                        mergeGroups(selectedRows)
                        setSelectedRows([])
                    }}
                >
                    Merge
                </LemonButton>
            )}
        </div>
    )
}
