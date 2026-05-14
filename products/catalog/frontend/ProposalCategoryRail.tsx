import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { catalogProposalsLogic } from './catalogProposalsLogic'
import { CategoryKey, PROPOSAL_CATEGORIES } from './proposalTypes'

export function ProposalCategoryRail(): JSX.Element {
    const { activeCategory, categoryCounts } = useValues(catalogProposalsLogic)
    const { setActiveCategory } = useActions(catalogProposalsLogic)

    return (
        <nav className="flex flex-col gap-1 p-2 border rounded bg-surface-primary text-sm w-60 shrink-0 self-start">
            {PROPOSAL_CATEGORIES.map((cat) => (
                <CategoryRow
                    key={cat.key}
                    label={cat.label}
                    icon={cat.iconLabel}
                    count={categoryCounts[cat.key] ?? 0}
                    active={activeCategory === cat.key}
                    onClick={() => setActiveCategory(cat.key)}
                />
            ))}
            <div className="my-2 border-t" />
            <div className="px-2 pt-1 pb-0.5 text-xs uppercase tracking-wide text-muted-alt">Audit</div>
            <CategoryRow
                label="Recently rejected"
                icon="✕"
                count={categoryCounts.rejected_relationships ?? 0}
                active={activeCategory === 'rejected_relationships'}
                onClick={() => setActiveCategory('rejected_relationships' as CategoryKey)}
            />
        </nav>
    )
}

interface CategoryRowProps {
    label: string
    icon: string
    count: number
    active: boolean
    onClick: () => void
}

function CategoryRow({ label, icon, count, active, onClick }: CategoryRowProps): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'flex items-center gap-2 px-2 py-1.5 rounded text-left transition-colors',
                active ? 'bg-primary-3000-highlight font-medium' : 'hover:bg-fill-highlight-50'
            )}
        >
            <span className="w-4 text-center text-muted-alt" aria-hidden>
                {icon}
            </span>
            <span className="flex-1 truncate">{label}</span>
            <span className={clsx('text-xs tabular-nums', active ? 'text-default' : 'text-muted-alt')}>{count}</span>
        </button>
    )
}
