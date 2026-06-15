import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconMegaphone, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag, Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { ExternalDataSourceType } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SourceIcon } from '../../shared/components/SourceIcon'
import { SourceReleaseTag } from '../../shared/components/SourceReleaseTag'
import { CatalogItem, sourceCatalogLogic } from './sourceCatalogLogic'

// "Request a data warehouse source" survey — shown when a user can't find the source they want.
const SOURCE_REQUEST_SURVEY_ID = '0190ff15-5032-0000-722a-e13933c140ac'

const TILE_CLASS =
    'flex flex-col items-center justify-center gap-2 p-4 h-40 rounded-lg border border-border bg-surface-primary text-center'

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
            <div className={TILE_CLASS}>
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
                <div className={`${TILE_CLASS} opacity-50 cursor-not-allowed`}>{inner}</div>
            </Tooltip>
        )
    }

    return (
        <Link to={item.url} className={`${TILE_CLASS} hover:border-primary cursor-pointer`} data-attr="catalog-source">
            {inner}
        </Link>
    )
}

function RequestSourceTile(): JSX.Element {
    return (
        <button
            type="button"
            className={`${TILE_CLASS} border-dashed hover:border-primary cursor-pointer`}
            onClick={() => posthog.displaySurvey(SOURCE_REQUEST_SURVEY_ID)}
            data-attr="catalog-request-source"
        >
            <IconPlusSmall className="text-2xl text-muted" />
            <div className="font-medium text-sm leading-tight">Request a source</div>
            <div className="text-xs text-muted">Tell us what you'd like to connect</div>
        </button>
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
            <div className="flex flex-row sm:flex-col gap-1 sm:w-56 sm:shrink-0 overflow-x-auto">
                {categoriesWithCounts.map((cat) => (
                    <LemonButton
                        key={cat.category}
                        active={selectedCategory === cat.category}
                        fullWidth
                        onClick={() => setSelectedCategory(cat.category)}
                        sideIcon={<span className="text-muted text-xs">{cat.count}</span>}
                    >
                        <span className="text-left">{cat.label}</span>
                    </LemonButton>
                ))}
            </div>

            <div className="flex flex-col gap-4 flex-1">
                <LemonInput type="search" placeholder="Search sources..." value={search} onChange={setSearch} />

                {filteredItems.length === 0 && (
                    <div className="text-muted text-sm">
                        No sources match.{' '}
                        <Link
                            onClick={() => {
                                setSearch('')
                                setSelectedCategory('all')
                            }}
                        >
                            Clear filters
                        </Link>{' '}
                        or request one below.
                    </div>
                )}

                <div className="grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-3">
                    {filteredItems.map((item) => (
                        <SourceTile
                            key={item.name}
                            item={item}
                            accessDisabledReason={accessDisabledReason}
                            onNotify={registerInterest}
                        />
                    ))}
                    <RequestSourceTile />
                </div>
            </div>
        </div>
    )
}
