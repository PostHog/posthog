import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyNumber } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { currencyFormatter } from 'scenes/billing/billing-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { GroupsQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GroupTypeIndex } from '~/types'

export function getCRMColumns(groupTypeName: string, groupTypeIndex: GroupTypeIndex): QueryContext['columns'] {
    return {
        group_name: {
            title: groupTypeName,
            render: function renderGroupName({ query, record, value }) {
                const sourceQuery = query.source as GroupsQuery
                const keyIndex = sourceQuery?.select?.indexOf('key') ?? -1
                const groupKey = (record as string[])[keyIndex]
                return (
                    <div className="min-w-40">
                        <LemonTableLink to={urls.group(groupTypeIndex, groupKey)} title={value as string} />
                        <CopyToClipboardInline
                            explicitValue={groupKey}
                            iconStyle={{ color: 'var(--color-accent)' }}
                            description="group id"
                        >
                            {stringWithWBR(groupKey, 100)}
                        </CopyToClipboardInline>
                    </div>
                )
            },
        },
        arr: {
            render: renderCurrency,
        },
        mrr: {
            render: renderCurrency,
        },
        'forecasted mrr': {
            render: renderCurrency,
        },
        owner: {
            render: renderPerson,
        },
        'survey responses': {
            render: renderLink,
        },
        'feature flags': {
            render: renderLink,
        },
        'mobile recordings': {
            render: renderLink,
        },
        'data warehouse': {
            render: renderLink,
        },
        events: {
            render: renderLink,
        },
    }
}

function renderCurrency({ value }: { value: unknown }): JSX.Element {
    if (!value || isNaN(Number(value))) {
        return <>—</>
    }
    return <LemonTableLink to={urls.revenueAnalytics()} title={currencyFormatter(value as number)} />
}

function renderPerson({ value }: { value: unknown }): JSX.Element {
    if (!value || typeof value !== 'string') {
        return <>—</>
    }
    return <PersonDisplay withIcon displayName={value as string} />
}

function renderLink({ value, columnName }: { value: unknown; columnName: string }): JSX.Element {
    if (!value || isNaN(Number(value))) {
        return <>—</>
    }

    const cellData = {
        value: value as string,
        title: humanFriendlyNumber(Number(value)),
        url: '',
        description: 'in the last 7d',
    }

    if (columnName === 'survey responses') {
        cellData['url'] = urls.surveys()
    } else if (columnName === 'feature flags') {
        cellData['url'] = urls.featureFlags()
        cellData['description'] = 'evals in the last 7d'
    } else if (columnName === 'mobile recordings') {
        cellData['url'] = urls.replay()
    } else if (columnName === 'data warehouse') {
        cellData['url'] = urls.sqlEditor()
        cellData['description'] = 'rows synced in the last 7d'
    } else if (columnName === 'events') {
        cellData['url'] = urls.activity()
    } else {
        return <>—</>
    }

    return (
        <div className="min-w-30">
            <LemonTableLink to={cellData.url} title={cellData.title} description={cellData.description} />
        </div>
    )
}
