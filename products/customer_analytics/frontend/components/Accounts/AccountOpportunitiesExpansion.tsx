import { useValues } from 'kea'

import { LemonSkeleton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { AccountOpportunity, accountOpportunitiesLogic, NOT_LOADED } from './accountOpportunitiesLogic'

function OpportunitiesEmptyState({ title, detail }: { title: string; detail: string }): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
            <BigLeaguesHog className="w-24 h-24" />
            <h4 className="mb-0">{title}</h4>
            <p className="text-secondary max-w-sm mb-0">{detail}</p>
        </div>
    )
}

function OpportunityDate({ value }: { value: string | null }): JSX.Element {
    if (!value) {
        return <span className="text-muted">—</span>
    }
    const parsed = dayjs(value)
    return <span>{parsed.isValid() ? parsed.format('MMM D, YYYY') : value}</span>
}

const columns: LemonTableColumns<AccountOpportunity> = [
    {
        title: 'Name',
        key: 'name',
        render: (_, opportunity) => opportunity.name || <span className="text-muted italic">Unnamed</span>,
        sorter: (a, b) => (a.name ?? '').localeCompare(b.name ?? ''),
    },
    {
        title: 'Credit amount',
        key: 'totalCreditAmount',
        align: 'right',
        render: (_, opportunity) =>
            opportunity.totalCreditAmount != null ? (
                humanFriendlyCurrency(opportunity.totalCreditAmount)
            ) : (
                <span className="text-muted">—</span>
            ),
        sorter: (a, b) => (a.totalCreditAmount ?? 0) - (b.totalCreditAmount ?? 0),
    },
    {
        title: 'Close date',
        key: 'closeDate',
        render: (_, opportunity) => <OpportunityDate value={opportunity.closeDate} />,
        sorter: (a, b) => dayjs(a.closeDate ?? 0).valueOf() - dayjs(b.closeDate ?? 0).valueOf(),
    },
    {
        title: 'Contract start',
        key: 'contractStartDate',
        render: (_, opportunity) => <OpportunityDate value={opportunity.contractStartDate} />,
        sorter: (a, b) => dayjs(a.contractStartDate ?? 0).valueOf() - dayjs(b.contractStartDate ?? 0).valueOf(),
    },
]

export function AccountOpportunitiesExpansion({ accountId }: { accountId: string }): JSX.Element {
    const { opportunitiesResult, opportunitiesResultLoading } = useValues(accountOpportunitiesLogic({ accountId }))

    if (opportunitiesResultLoading || opportunitiesResult === NOT_LOADED) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    const { sfdcId, opportunities } = opportunitiesResult

    if (!sfdcId) {
        return (
            <OpportunitiesEmptyState
                title="Not linked to Salesforce"
                detail="This account doesn't have a Salesforce ID, so there are no opportunities to show."
            />
        )
    }

    if (!opportunities || opportunities.length === 0) {
        return (
            <OpportunitiesEmptyState
                title="No opportunities yet"
                detail="We couldn't find any Salesforce opportunities for this account."
            />
        )
    }

    return (
        <LemonTable<AccountOpportunity>
            size="small"
            embedded
            dataSource={opportunities}
            columns={columns}
            rowKey="id"
        />
    )
}
