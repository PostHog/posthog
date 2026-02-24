import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyNumber } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { currencyFormatter } from 'scenes/billing/billing-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { QueryContext } from '~/queries/types'

export function getCRMColumns(groupTypeName: string, groupTypeIndex: number): QueryContext['columns'] {
    return {
        group_name: {
            title: groupTypeName,
            render: function renderGroupName({ value }) {
                if (typeof value === 'object' && value !== null && 'display_name' in value && 'key' in value) {
                    return (
                        <div className="min-w-40">
                            <LemonTableLink
                                to={urls.group(groupTypeIndex, value.key as string)}
                                title={value.display_name as string}
                            />
                            <CopyToClipboardInline
                                explicitValue={value.key as string}
                                iconStyle={{ color: 'var(--color-accent)' }}
                                description="group id"
                            >
                                {stringWithWBR(value.key as string, 100)}
                            </CopyToClipboardInline>
                        </div>
                    )
                }
                return <>{String(value)}</>
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
