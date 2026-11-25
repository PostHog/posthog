import { ReactNode } from 'react'

import { IconPerson } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { PersonListItemApi } from '../../../generated/api.schemas'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { formatCostUsd } from '../../shared/formatCost'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import { TracePersonCell } from '../../traces/components/TracePersonCell'
import type { PersonFirstSeen } from '../types'
import { PersonFirstSeenCell } from './PersonFirstSeenCell'

export interface PersonDrawerHeaderProps {
    person: PersonListItemApi
    /** Null until it is asked for. */
    firstSeen: TraceCellLoad<PersonFirstSeen> | null
    personHref: string | null
}

function Tile({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex min-w-28 flex-1 flex-col gap-0.5 rounded border border-primary px-2 py-1.5">
            <span className="text-xs text-secondary">{label}</span>
            <span className="font-semibold">{children}</span>
        </div>
    )
}

export function PersonDrawerHeader({ person, firstSeen, personHref }: PersonDrawerHeaderProps): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 text-base font-semibold">
                    <TracePersonCell person={person.person} status="ready" maxWidthClassName="max-w-full" />
                </span>
                {personHref ? (
                    <LemonButton
                        className="ml-auto"
                        size="small"
                        type="secondary"
                        icon={<IconPerson />}
                        to={personHref}
                        // pinned: autocapture dashboards select the profile link by this value
                        data-attr="ai-observability-person-drawer-profile"
                    >
                        View person
                    </LemonButton>
                ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
                <Tile label="Sessions">{humanFriendlyNumber(person.sessionCount)}</Tile>
                <Tile label="Traces">{humanFriendlyNumber(person.traceCount)}</Tile>
                <Tile label="Cost">{person.cost !== null ? formatCostUsd(person.cost) : '-'}</Tile>
                <Tile label="Last seen">
                    <ShortTimestamp time={person.lastSeen} />
                </Tile>
            </div>
            <div className="flex items-center gap-1 text-secondary">
                <span>First seen</span>
                <PersonFirstSeenCell
                    firstSeen={firstSeen?.status === 'ready' ? firstSeen.value : null}
                    status={firstSeen?.status ?? 'loading'}
                />
            </div>
        </div>
    )
}
