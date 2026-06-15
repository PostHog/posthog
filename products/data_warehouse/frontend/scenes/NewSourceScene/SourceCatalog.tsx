import { useActions, useValues } from 'kea'

import { IconMegaphone } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag, Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { ExternalDataSourceType } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SourceIcon } from '../../shared/components/SourceIcon'
import { SourceReleaseTag } from '../../shared/components/SourceReleaseTag'
import { CatalogItem, sourceCatalogLogic } from './sourceCatalogLogic'

export interface SourceCatalogProps {
    allowedSources?: ExternalDataSourceType[]
}

function SourceTile({
    item,
    accessDisabledReason,
    onNotify,
}: {
    item: CatalogItem
    accessDisabledReason: string | null
    onNotify: (item: CatalogItem) => void
}): JSX.Element {
    const tileClass =
        'flex flex-col items-center justify-center gap-2 p-4 h-32 rounded-lg border border-border bg-surface-primary text-center'

    const inner = (
        <>
            <SourceIcon type={item.iconType} size="medium" disableTooltip />
            <div className="font-medium text-sm leading-tight">{item.label}</div>
            <div className="flex items-center gap-1">
                {item.status === 'coming_soon' ? (
                    <LemonTag type="warning">Coming soon</LemonTag>
                ) : (
                    <SourceReleaseTag releaseStatus={item.releaseStatus} />
                )}
            </div>
        </>
    )

    if (item.status === 'coming_soon') {
        return (
            <div className={`${tileClass} relative`}>
                {inner}
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconMegaphone />}
                    onClick={() => onNotify(item)}
                    data-attr="catalog-notify-me"
                >
                    Notify me
                </LemonButton>
            </div>
        )
    }

    if (accessDisabledReason) {
        return (
            <Tooltip title={accessDisabledReason}>
                <div className={`${tileClass} opacity-50 cursor-not-allowed`}>{inner}</div>
            </Tooltip>
        )
    }

    return (
        <Link to={item.url} className={`${tileClass} hover:border-primary cursor-pointer`} data-attr="catalog-source">
            {inner}
        </Link>
    )
}

export function SourceCatalog({ allowedSources }: SourceCatalogProps): JSX.Element {
    const logic = sourceCatalogLogic({ allowedSources })
    const { filteredItems, categoriesWithCounts, search, selectedCategory } = useValues(logic)
    const { setSearch, setSelectedCategory, registerInterest } = useActions(logic)

    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.ExternalDataSource,
        AccessControlLevel.Editor
    )

    return (
        <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex flex-row sm:flex-col gap-1 sm:w-48 sm:shrink-0 overflow-x-auto">
                {categoriesWithCounts.map((cat) => (
                    <LemonButton
                        key={cat.category}
                        active={selectedCategory === cat.category}
                        fullWidth
                        onClick={() => setSelectedCategory(cat.category)}
                        sideIcon={<span className="text-muted text-xs">{cat.count}</span>}
                    >
                        <span className="whitespace-nowrap">{cat.label}</span>
                    </LemonButton>
                ))}
            </div>

            <div className="flex flex-col gap-4 flex-1">
                <LemonInput type="search" placeholder="Search sources..." value={search} onChange={setSearch} />

                {filteredItems.length === 0 ? (
                    <div className="text-muted text-center py-8">
                        No sources found.{' '}
                        <Link
                            onClick={() => {
                                setSearch('')
                                setSelectedCategory('all')
                            }}
                        >
                            Clear filters
                        </Link>
                    </div>
                ) : (
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                        {filteredItems.map((item) => (
                            <SourceTile
                                key={item.name}
                                item={item}
                                accessDisabledReason={accessDisabledReason}
                                onNotify={registerInterest}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
