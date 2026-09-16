import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown } from '@posthog/lemon-ui'

import { batchExportRunsLogic } from './batchExportRunsLogic'
import { BATCH_EXPORT_RUN_STATUS_FILTER_OPTIONS, BatchExportRunStatusGroup } from './utils'

function summarize(selected: BatchExportRunStatusGroup[]): string {
    if (selected.length === 0 || selected.length === BATCH_EXPORT_RUN_STATUS_FILTER_OPTIONS.length) {
        return 'All statuses'
    }
    if (selected.length === 1) {
        return BATCH_EXPORT_RUN_STATUS_FILTER_OPTIONS.find((option) => option.value === selected[0])?.label ?? 'Status'
    }
    return `${selected.length} statuses`
}

export function BatchExportRunStatusFilter({ id }: { id: string }): JSX.Element {
    const { statusFilter } = useValues(batchExportRunsLogic({ id }))
    const { setStatusFilter } = useActions(batchExportRunsLogic({ id }))

    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="flex flex-col gap-px p-1">
                    {BATCH_EXPORT_RUN_STATUS_FILTER_OPTIONS.map((option) => (
                        <LemonButton
                            key={option.value}
                            type="tertiary"
                            size="small"
                            fullWidth
                            icon={
                                <LemonCheckbox
                                    checked={statusFilter.includes(option.value)}
                                    className="pointer-events-none"
                                />
                            }
                            onClick={() =>
                                setStatusFilter(
                                    statusFilter.includes(option.value)
                                        ? statusFilter.filter((value) => value !== option.value)
                                        : [...statusFilter, option.value]
                                )
                            }
                        >
                            {option.label}
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                data-attr="batch-export-runs-status-filter"
            >
                {summarize(statusFilter)}
            </LemonButton>
        </LemonDropdown>
    )
}
