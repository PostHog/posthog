import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'

import { QueryContextColumn } from '~/queries/types'

import { AccountNameCell } from '../Accounts/AccountNameCell'
import { AccountRelationshipHolders } from '../Accounts/AccountRelationshipHolders'
import { ACCOUNTS_NAME_COLUMN, accountsColumnConfigLogic } from '../Accounts/accountsColumnConfigLogic'
import { CustomPropertyValueDisplay } from '../Accounts/CustomPropertyValueDisplay'
import { accountAudienceTableLogic } from './accountAudienceTableLogic'

const NAME_COLUMN_WIDTH = '280px'
const RELATIONSHIP_COLUMN_WIDTH = '220px'

interface AccountAudienceNameValue {
    id: string
    name: string
    external_id: string | null
    logo_domain: string | null
}

function isAccountAudienceNameValue(value: unknown): value is AccountAudienceNameValue {
    return (
        typeof value === 'object' &&
        value !== null &&
        typeof (value as AccountAudienceNameValue).id === 'string' &&
        typeof (value as AccountAudienceNameValue).name === 'string'
    )
}

function parseUserIds(value: unknown): number[] {
    return Array.isArray(value) ? value.map(Number).filter((id) => Number.isFinite(id)) : []
}

function SortableHeader({ column, label }: { column: string; label: string }): JSX.Element {
    const { sortOrder } = useValues(accountAudienceTableLogic)
    const { toggleSort } = useActions(accountAudienceTableLogic)
    const order = sortOrder?.column === column ? (sortOrder.direction === 'asc' ? 1 : -1) : null
    return (
        <button
            type="button"
            className="inline-flex items-center cursor-pointer select-none bg-transparent border-0 p-0 font-semibold"
            onClick={() => toggleSort(column)}
            data-attr={`account-audience-sort-${column}`}
        >
            {label}
            <SortingIndicator order={order} />
        </button>
    )
}

function NameCell({ value }: { value: unknown }): JSX.Element {
    const { reportAccountOpened } = useActions(accountAudienceTableLogic)
    if (!isAccountAudienceNameValue(value)) {
        return <span className="text-muted">—</span>
    }
    return (
        <AccountNameCell
            accountId={value.id}
            name={value.name}
            externalId={value.external_id}
            logoDomain={value.logo_domain}
            target="_blank"
            onClick={reportAccountOpened}
        />
    )
}

function TagsCell({ value }: { value: unknown }): JSX.Element {
    const tags = Array.isArray(value) ? value.filter((tag): tag is string => typeof tag === 'string') : []
    return tags.length > 0 ? <ObjectTags tags={tags} staticOnly /> : <span className="text-muted">—</span>
}

function NotebookCountCell({ value }: { value: unknown }): JSX.Element {
    const count = Number(value) || 0
    return count > 0 ? <span>{count}</span> : <span className="text-muted">—</span>
}

export function useAccountAudienceTableColumns(): Record<string, QueryContextColumn> {
    const { visibleColumnNames, aliasToDefinition, aliasToRelationshipDefinition, displayByAlias } =
        useValues(accountsColumnConfigLogic)

    return useMemo(() => {
        const columns: Record<string, QueryContextColumn> = {}
        for (const key of visibleColumnNames) {
            const definition = aliasToDefinition[key]
            if (definition) {
                const display = displayByAlias[key]
                columns[key] = {
                    renderTitle: () => <SortableHeader column={key} label={definition.name} />,
                    render: ({ value }) => (
                        <CustomPropertyValueDisplay raw={value} definition={definition} display={display} />
                    ),
                }
                continue
            }
            const relationshipDefinition = aliasToRelationshipDefinition[key]
            if (relationshipDefinition) {
                columns[key] = {
                    renderTitle: () => <SortableHeader column={key} label={relationshipDefinition.name} />,
                    width: RELATIONSHIP_COLUMN_WIDTH,
                    render: ({ value }) => <AccountRelationshipHolders userIds={parseUserIds(value)} column={key} />,
                }
                continue
            }
            if (key === ACCOUNTS_NAME_COLUMN) {
                columns[key] = {
                    renderTitle: () => <SortableHeader column={key} label="Account" />,
                    width: NAME_COLUMN_WIDTH,
                    render: ({ value }) => <NameCell value={value} />,
                }
                continue
            }
            if (key === 'tag_names') {
                columns[key] = {
                    renderTitle: () => <SortableHeader column={key} label="Tags" />,
                    render: ({ value }) => <TagsCell value={value} />,
                }
                continue
            }
            if (key === 'notebook_count') {
                columns[key] = {
                    renderTitle: () => <SortableHeader column={key} label="Notes" />,
                    render: ({ value }) => <NotebookCountCell value={value} />,
                }
                continue
            }
            columns[key] = { renderTitle: () => <SortableHeader column={key} label={key} /> }
        }
        return columns
    }, [visibleColumnNames, aliasToDefinition, aliasToRelationshipDefinition, displayByAlias])
}
