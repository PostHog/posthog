import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { IconMegaphone, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTag, LemonTextArea, Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { ExternalDataSourceType } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SourceIcon } from '../../shared/components/SourceIcon'
import { SourceReleaseTag } from '../../shared/components/SourceReleaseTag'
import { WarehouseWizardHint } from '../../shared/components/WarehouseWizardHint'
import { CatalogItem, sourceCatalogLogic } from './sourceCatalogLogic'

// Horizontal card: logo on the left, name/status/action stacked on the right. `min-h` (not a fixed
// height) so a wrapped name plus the "Notify me" button can never clip.
const TILE_CLASS =
    'flex flex-row items-center gap-4 p-5 min-h-[8.5rem] rounded-lg border border-border bg-surface-primary'

export interface SourceCatalogProps {
    allowedSources?: ExternalDataSourceType[]
}

// Memoized so the whole grid doesn't re-render per keystroke in the search input or request
// modal: item references are stable across unrelated updates (catalogItems has a result
// equality check) and the callbacks are kea actions.
const SourceTile = memo(function SourceTile({
    item,
    accessDisabledReason,
    onNotify,
    onSelect,
}: {
    item: CatalogItem
    accessDisabledReason: string | null
    onNotify: (item: CatalogItem) => void
    onSelect: (item: CatalogItem) => void
}): JSX.Element {
    const content = (
        <>
            <div className="shrink-0">
                <SourceIcon type={item.iconType} size="medium" disableTooltip />
            </div>
            <div className="flex flex-col items-start gap-2 min-w-0 text-left">
                <div className="font-medium text-sm leading-tight line-clamp-2">{item.label}</div>
                {item.status === 'coming_soon' ? (
                    <>
                        <LemonTag type="warning">Coming soon</LemonTag>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            icon={<IconMegaphone />}
                            onClick={() => onNotify(item)}
                            data-attr="catalog-notify-me"
                        >
                            Notify me
                        </LemonButton>
                    </>
                ) : (
                    <SourceReleaseTag releaseStatus={item.releaseStatus} />
                )}
            </div>
        </>
    )

    if (item.status === 'coming_soon') {
        return <div className={TILE_CLASS}>{content}</div>
    }

    if (accessDisabledReason) {
        return (
            <Tooltip title={accessDisabledReason}>
                <div className={`${TILE_CLASS} opacity-50 cursor-not-allowed`}>{content}</div>
            </Tooltip>
        )
    }

    return (
        <Link
            to={item.url}
            className={`${TILE_CLASS} hover:border-primary cursor-pointer`}
            data-attr="catalog-source"
            onClick={() => onSelect(item)}
        >
            {content}
        </Link>
    )
})

function RequestSourceTile({ onRequest }: { onRequest: () => void }): JSX.Element {
    return (
        <button
            type="button"
            className={`${TILE_CLASS} border-dashed hover:border-primary cursor-pointer text-left`}
            onClick={onRequest}
            data-attr="catalog-request-source"
        >
            <div className="shrink-0 flex items-center justify-center w-[60px]">
                <IconPlusSmall className="text-3xl text-muted" />
            </div>
            <div className="flex flex-col items-start gap-2 min-w-0">
                <div className="font-medium text-sm leading-tight">Request a source</div>
                <div className="text-xs text-muted">Tell us what you'd like to connect</div>
            </div>
        </button>
    )
}

export function SourceCatalog({ allowedSources }: SourceCatalogProps): JSX.Element {
    const logic = sourceCatalogLogic({ allowedSources })
    const {
        filteredItems,
        categoriesWithCounts,
        search,
        selectedCategory,
        sourceRequestModalOpen,
        sourceRequestText,
        popularItems,
        showPopularSection,
    } = useValues(logic)
    const {
        setSearch,
        setSelectedCategory,
        registerInterest,
        showSourceRequest,
        hideSourceRequest,
        setSourceRequestText,
        submitSourceRequest,
        selectSourceType,
    } = useActions(logic)

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
                <WarehouseWizardHint />
                <LemonInput type="search" placeholder="Search sources..." value={search} onChange={setSearch} />

                {showPopularSection && (
                    <div className="flex flex-col gap-2">
                        <h3 className="text-sm font-semibold text-muted mb-0">Popular sources</h3>
                        <div className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
                            {popularItems.map((item) => (
                                <SourceTile
                                    key={item.name}
                                    item={item}
                                    accessDisabledReason={accessDisabledReason}
                                    onNotify={registerInterest}
                                    onSelect={selectSourceType}
                                />
                            ))}
                        </div>
                    </div>
                )}

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

                <div className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
                    {filteredItems.map((item) => (
                        <SourceTile
                            key={item.name}
                            item={item}
                            accessDisabledReason={accessDisabledReason}
                            onNotify={registerInterest}
                            onSelect={selectSourceType}
                        />
                    ))}
                    <RequestSourceTile onRequest={showSourceRequest} />
                </div>
            </div>

            <LemonModal
                isOpen={sourceRequestModalOpen}
                onClose={hideSourceRequest}
                title="Request a source"
                description="Tell us which source you'd like to connect and we'll take it into account."
                footer={
                    <>
                        <LemonButton type="secondary" onClick={hideSourceRequest}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={submitSourceRequest}
                            disabledReason={!sourceRequestText.trim() ? 'Describe the source first' : undefined}
                            data-attr="catalog-request-source-submit"
                        >
                            Submit request
                        </LemonButton>
                    </>
                }
            >
                <LemonTextArea
                    value={sourceRequestText}
                    onChange={setSourceRequestText}
                    placeholder="e.g. Acme CRM — https://acme.com/developers/api"
                    minRows={3}
                    autoFocus
                />
            </LemonModal>
        </div>
    )
}
