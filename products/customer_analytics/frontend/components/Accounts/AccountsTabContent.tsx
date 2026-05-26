import { AccountsTabFilters } from './AccountsTabFilters'
import { AccountsTable } from './AccountsTable'

export function AccountsTabContent(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <AccountsTabFilters />
            <AccountsTable />
        </div>
    )
}
