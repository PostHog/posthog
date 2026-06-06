import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

type EditWidgetModalFiltersSectionProps = {
    filterTestAccounts: boolean
    saving: boolean
    setFilterTestAccounts: (value: boolean) => void
}

export function EditWidgetModalFiltersSection({
    filterTestAccounts,
    saving,
    setFilterTestAccounts,
}: EditWidgetModalFiltersSectionProps): JSX.Element {
    return (
        <section className="flex flex-col gap-3">
            <h5 className="text-sm font-semibold m-0">Filters</h5>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="sm:col-span-2">
                    <TestAccountFilter
                        size="small"
                        filters={{ filter_test_accounts: filterTestAccounts }}
                        onChange={({ filter_test_accounts }) => setFilterTestAccounts(filter_test_accounts ?? false)}
                        disabledReason={saving ? 'Saving…' : undefined}
                    />
                </div>
            </div>
        </section>
    )
}
