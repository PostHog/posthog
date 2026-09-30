import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconCopy, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSnack, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { AnyPropertyFilter } from '~/types'

import type { AccountPersonApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    ACCOUNT_FIRST_SEEN_KEY,
    ACCOUNT_LAST_SEEN_KEY,
    ACCOUNT_PERSONS_PAGE_SIZE,
    EMAIL_PROPERTY_KEY,
    MAX_PERSON_PROPERTY_COLUMNS,
    personEmail,
    personPropertyDisplayValue,
    propertyColumnKey,
} from './accountPersons'
import { ACCOUNT_PERSONS_READ_SOURCE, accountPersonsLogic, type AccountPersonsViewState } from './accountPersonsLogic'
import type { AccountViewTileLogicProps } from './accountViewTileConfig'
import { AccountsEvents } from './constants'

interface AccountPersonsExpansionProps extends AccountViewTileLogicProps {
    accountId: string
    embedded?: boolean
}

function PersonsEmptyState({
    viewState,
    onRetry,
}: {
    viewState: Exclude<AccountPersonsViewState, 'loading' | 'loaded'>
    onRetry: () => void
}): JSX.Element {
    if (viewState === 'error') {
        return (
            <div className="flex flex-col items-center gap-2 py-4" data-attr="customer-analytics-account-persons-error">
                <span>
                    Couldn't load people for this account. Try again, and if it keeps happening contact support.
                </span>
                <LemonButton type="secondary" size="small" onClick={onRetry}>
                    Try again
                </LemonButton>
            </div>
        )
    }
    return (
        <span data-attr={`customer-analytics-account-persons-${viewState === 'empty' ? 'empty' : 'filtered-empty'}`}>
            {viewState === 'empty'
                ? 'No people are associated with this account yet.'
                : 'No people match your search or filters. Change or clear them to see more.'}
        </span>
    )
}

export function AccountPersonsExpansion({
    accountId,
    embedded = true,
    ...tileProps
}: AccountPersonsExpansionProps): JSX.Element {
    const logic = accountPersonsLogic({ accountId, ...tileProps })
    const {
        persons,
        personsResponseLoading,
        viewState,
        hasMore,
        page,
        searchTerm,
        propertyFilters,
        propertyColumns,
        selectedPropertyKeys,
        sorting,
    } = useValues(logic)
    const {
        setPage,
        setSearchTerm,
        setSorting,
        setPropertyFilters,
        addPropertyColumn,
        removePropertyColumn,
        copyEmails,
        loadPersons,
    } = useActions(logic)
    const [bulkBarTarget, setBulkBarTarget] = useState<HTMLDivElement | null>(null)

    const propertyTableColumns: LemonTableColumns<AccountPersonApi> = propertyColumns.map((propertyKey) => ({
        title: propertyKey,
        key: propertyColumnKey(propertyKey),
        sorter: true,
        render: (_, person) => {
            const value = personPropertyDisplayValue(person.properties[propertyKey])
            return value === null ? (
                <span className="text-muted">-</span>
            ) : (
                <span className="block max-w-64 truncate" title={value}>
                    {value}
                </span>
            )
        },
    }))

    const columns: LemonTableColumns<AccountPersonApi> = [
        {
            title: 'Person',
            key: 'name',
            render: (_, person) => (
                <Link
                    to={urls.personByUUID(person.id)}
                    className="font-medium"
                    onClick={() =>
                        posthog.capture(AccountsEvents.RelatedUserClicked, { read_source: ACCOUNT_PERSONS_READ_SOURCE })
                    }
                >
                    {person.name}
                </Link>
            ),
        },
        {
            title: 'Email',
            key: propertyColumnKey(EMAIL_PROPERTY_KEY),
            sorter: true,
            render: (_, person) => {
                const email = personEmail(person)
                return email ? (
                    <span className="text-sm text-muted">{email}</span>
                ) : (
                    <span className="text-sm text-muted">No email</span>
                )
            },
        },
        {
            title: 'First activity',
            key: ACCOUNT_FIRST_SEEN_KEY,
            sorter: true,
            render: (_, person) => <TZLabel time={person.account_first_seen} />,
        },
        {
            title: 'Last activity',
            key: ACCOUNT_LAST_SEEN_KEY,
            sorter: true,
            render: (_, person) => <TZLabel time={person.account_last_seen} />,
        },
        ...propertyTableColumns,
    ]

    return (
        <div className="@container flex flex-col gap-2" data-attr="customer-analytics-account-persons">
            <div className="flex flex-wrap items-center gap-2" data-attr="customer-analytics-account-users-toolbar">
                <LemonInput
                    type="search"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    placeholder="Search name, email, or ID"
                    maxLength={200}
                    size="small"
                    className="w-full @min-[36rem]:w-72"
                    data-attr="customer-analytics-account-users-search"
                />
                <TaxonomicPopover
                    groupType={TaxonomicFilterGroupType.PersonProperties}
                    excludedProperties={{ [TaxonomicFilterGroupType.PersonProperties]: selectedPropertyKeys }}
                    onChange={(propertyKey) => addPropertyColumn(String(propertyKey))}
                    placeholder="Add column"
                    icon={<IconPlusSmall />}
                    size="small"
                    disabledReason={
                        propertyColumns.length >= MAX_PERSON_PROPERTY_COLUMNS
                            ? `You can add up to ${MAX_PERSON_PROPERTY_COLUMNS} property columns`
                            : undefined
                    }
                    data-attr="customer-analytics-account-users-add-column"
                />
                <div ref={setBulkBarTarget} className="flex items-center empty:hidden" />
            </div>
            <PropertyFilters
                propertyFilters={propertyFilters}
                onChange={(filters: AnyPropertyFilter[]) => setPropertyFilters(filters)}
                pageKey={`customer-analytics-account-persons-${accountId}`}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                buttonSize="small"
                buttonText="Filter"
            />
            {propertyColumns.length > 0 && (
                <div className="flex flex-wrap items-center gap-1" data-attr="customer-analytics-account-users-columns">
                    {propertyColumns.map((propertyKey) => (
                        <LemonSnack key={propertyKey} onClose={() => removePropertyColumn(propertyKey)}>
                            {propertyKey}
                        </LemonSnack>
                    ))}
                </div>
            )}
            <LemonTable<AccountPersonApi>
                key={accountId}
                size="small"
                embedded={embedded}
                dataSource={persons}
                rowKey="id"
                loading={personsResponseLoading}
                columns={columns}
                sorting={sorting}
                onSort={setSorting}
                useURLForSorting={false}
                nouns={['person', 'people']}
                pagination={{
                    controlled: true,
                    pageSize: ACCOUNT_PERSONS_PAGE_SIZE,
                    currentPage: page,
                    useUrl: false,
                    onBackward: () => setPage(page - 1),
                    // The API reports only whether another page exists, so no forward handler means the last page.
                    onForward: hasMore ? () => setPage(page + 1) : undefined,
                }}
                bulkSelection={{
                    getKey: (person) => personEmail(person) ?? person.id,
                    isRowSelectable: (person) =>
                        personEmail(person) ? true : { disabledReason: 'This person has no email address' },
                    noun: ['person', 'people'],
                    rowAriaLabel: (person) => `Select ${person.name}`,
                    headerAriaLabel: 'Select all people on this page',
                    barPortalTarget: bulkBarTarget,
                    renderActions: (context) => (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconCopy />}
                            data-attr="customer-analytics-account-users-copy-emails"
                            onClick={() => copyEmails(context.selectedKeys.map(String))}
                        >
                            Copy email addresses
                        </LemonButton>
                    ),
                }}
                emptyState={
                    viewState === 'loading' || viewState === 'loaded' ? undefined : (
                        <PersonsEmptyState viewState={viewState} onRetry={() => loadPersons()} />
                    )
                }
                data-attr="customer-analytics-account-persons-table"
            />
        </div>
    )
}
