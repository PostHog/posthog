import { LemonInput, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DatabaseTablesContainer } from 'scenes/data-management/database/DatabaseTables'

import { databaseTableListLogic } from './databaseTableListLogic'

export function DatabaseTableList(): JSX.Element {
    const { searchTerm } = useValues(databaseTableListLogic)
    const { setSearchTerm } = useActions(databaseTableListLogic)

    return (
        <div data-attr="database-list">
            <div className="flex items-center justify-between gap-2 mb-4">
                <LemonInput type="search" placeholder="Search for tables" onChange={setSearchTerm} value={searchTerm} />
            </div>
            <div className="flex items-center justify-between gap-2 mb-4">
                <div>
                    These are the database tables you can query under SQL insights with{' '}
                    <Link to="https://posthog.com/manual/hogql" target="_blank">
                        HogQL
                    </Link>
                    .
                </div>
            </div>
            <DatabaseTablesContainer />
        </div>
    )
}
