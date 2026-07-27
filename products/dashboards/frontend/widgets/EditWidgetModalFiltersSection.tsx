import type { ReactNode } from 'react'

import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

type EditWidgetModalTestAccountFilterProps = {
    filterTestAccounts: boolean
    saving: boolean
    setFilterTestAccounts: (value: boolean) => void
}

export function EditWidgetModalTestAccountFilter({
    filterTestAccounts,
    saving,
    setFilterTestAccounts,
}: EditWidgetModalTestAccountFilterProps): JSX.Element {
    return (
        <div className="sm:col-span-2">
            <TestAccountFilter
                size="small"
                filters={{ filter_test_accounts: filterTestAccounts }}
                onChange={({ filter_test_accounts }) => setFilterTestAccounts(filter_test_accounts ?? false)}
                disabledReason={saving ? 'Saving…' : undefined}
            />
        </div>
    )
}

export type EditWidgetModalFiltersSubsectionProps = EditWidgetModalTestAccountFilterProps & {
    /** Subsection heading under the product group (e.g. "Issue filters"). */
    title: string
    children?: ReactNode
}

/** Test-account filter plus optional fields in a 2-column grid (matches error tracking widget modal). */
export function EditWidgetModalFiltersSubsection({
    title,
    filterTestAccounts,
    saving,
    setFilterTestAccounts,
    children,
}: EditWidgetModalFiltersSubsectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <h6 className="text-xs font-semibold text-muted m-0">{title}</h6>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <EditWidgetModalTestAccountFilter
                    filterTestAccounts={filterTestAccounts}
                    saving={saving}
                    setFilterTestAccounts={setFilterTestAccounts}
                />
                {children}
            </div>
        </div>
    )
}
