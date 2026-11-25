import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import type { PersonListItemApi } from '../../../generated/api.schemas'
import { formatCostUsd } from '../../shared/formatCost'

export interface ExpensivePeopleSectionProps {
    /** Null while the people load, or after a failed read. */
    people: PersonListItemApi[] | null
    /** True while a read is in flight, so rows of the previous range never show. */
    loading: boolean
    failed: boolean
    needsIdentification: boolean
    docsUrl: string
    onRetry: () => void
    personHref: (person: Pick<PersonListItemApi, 'id'>) => string
    viewAllHref: string
}

const SKELETON_ROWS = 5

function Message({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="flex min-h-24 flex-col items-center justify-center gap-1 text-center">{children}</div>
}

function PersonRow({
    person,
    topCost,
    href,
}: {
    person: PersonListItemApi
    topCost: number
    href: string
}): JSX.Element {
    const share = person.cost !== null && topCost > 0 ? (person.cost / topCost) * 100 : 0
    return (
        <Link
            to={href}
            subtle
            className="flex min-w-0 flex-col gap-1 rounded p-1 hover:bg-surface-secondary"
            // pinned: data-attrs feed autocapture; dashboards and tests find the row by this value
            data-attr="home-expensive-person"
        >
            <div className="flex min-w-0 items-center justify-between gap-2">
                <span className="ph-no-capture min-w-0 truncate" title={person.person.label}>
                    <PersonDisplay
                        person={{ distinct_id: person.person.distinctId, properties: {} }}
                        displayName={person.person.label}
                        withIcon="sm"
                        noLink
                        noPopover
                    />
                </span>
                <span className="whitespace-nowrap text-sm tabular-nums" translate="no">
                    {person.cost !== null ? formatCostUsd(person.cost) : '-'}
                </span>
            </div>
            <div className="h-1 rounded bg-surface-secondary">
                {share > 0 ? (
                    <div
                        className="h-1 rounded bg-accent"
                        style={{ width: `${share}%` }}
                        data-attr="home-expensive-person-bar"
                    />
                ) : null}
            </div>
        </Link>
    )
}

function Body({
    people,
    loading,
    failed,
    needsIdentification,
    docsUrl,
    onRetry,
    personHref,
}: ExpensivePeopleSectionProps): JSX.Element {
    if (failed) {
        return (
            <Message>
                <span className="text-sm text-secondary">Could not load the people</span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={onRetry}
                    // pinned: data-attrs feed autocapture; tests find the retry by this value
                    data-attr="home-expensive-people-retry"
                >
                    Retry
                </LemonButton>
            </Message>
        )
    }
    if (loading || people === null) {
        return (
            <div className="flex flex-col gap-3">
                {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                    <LemonSkeleton key={index} className="h-6 w-full" />
                ))}
            </div>
        )
    }
    if (needsIdentification) {
        return (
            <Message>
                <span className="text-base font-semibold text-secondary">Not set up</span>
                <Link
                    to={docsUrl}
                    target="_blank"
                    className="text-xs"
                    // pinned: data-attrs feed autocapture; dashboards and tests find the setup link by this value
                    data-attr="home-expensive-people-not-set-up"
                >
                    Identify your users
                </Link>
            </Message>
        )
    }
    if (people.length === 0) {
        return (
            <Message>
                <span className="text-sm text-secondary">No people in this range</span>
            </Message>
        )
    }
    const topCost = Math.max(...people.map((person) => person.cost ?? 0))
    return (
        <div className="flex flex-col gap-1">
            {people.map((person) => (
                <PersonRow key={person.id} person={person} topCost={topCost} href={personHref(person)} />
            ))}
        </div>
    )
}

export function ExpensivePeopleSection(props: ExpensivePeopleSectionProps): JSX.Element {
    return (
        // pinned: data-attrs feed autocapture; dashboards and tests find the section by this value
        <section
            className="flex min-w-0 flex-col gap-3 rounded border bg-surface-primary p-3"
            data-attr="home-section-expensive-users"
        >
            <div className="flex min-h-7 flex-wrap items-center justify-between gap-2">
                <h3 className="m-0 text-sm font-semibold">Most expensive users</h3>
                <Link to={props.viewAllHref} subtle className="text-xs" data-attr="home-expensive-people-view-all">
                    View all
                </Link>
            </div>
            <Body {...props} />
        </section>
    )
}
