import { useActions, useValues } from 'kea'

import { IconStar, IconStarFilled } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, Spinner } from '@posthog/lemon-ui'

import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { sidebarProductMeta } from '../../sidebarProductMeta'
import { JevProductSuggestions } from './JevProductSuggestions'
import { NavProductIcon } from './NavProductIcon'
import { navProductsTabLogic } from './navProductsTabLogic'
import { NavProductTooltip } from './NavProductTooltip'
import { productsItemName } from './productsCatalog'

export function StarredProductsPicker(): JSX.Element {
    const {
        customizeProductGroups,
        draftStarredPaths,
        customizeSearch,
        customizeSidebarMode,
        customProducts,
        appRecommendationsEnabled,
    } = useValues(navProductsTabLogic)
    const { setDraftStarred, setCustomizeSearch, unselectAllStarred } = useActions(navProductsTabLogic)
    const { shortcutDataHasLoaded } = useValues(projectTreeDataLogic)

    return (
        <section className="@container flex flex-col gap-3 group/colorful-product-icons colorful-product-icons-true">
            <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
                <div>
                    <LemonLabel>Starred</LemonLabel>
                    <p className="text-xs text-secondary mb-0">
                        {customizeSidebarMode === 'starred-setup' && customProducts.length > 0
                            ? 'Your custom products and existing stars are already picked.'
                            : 'Star the products you want to see in your sidebar.'}
                    </p>
                </div>
                {shortcutDataHasLoaded && (
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-secondary">{`${draftStarredPaths.size} starred`}</span>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            onClick={unselectAllStarred}
                            disabledReason={draftStarredPaths.size === 0 ? 'Nothing is starred' : undefined}
                            data-attr="customize-sidebar-unselect-all"
                        >
                            Unselect all
                        </LemonButton>
                    </div>
                )}
            </div>
            {customizeSidebarMode === 'customize' && appRecommendationsEnabled && <JevProductSuggestions />}
            <LemonInput
                type="search"
                size="small"
                placeholder="Search products"
                value={customizeSearch}
                onChange={setCustomizeSearch}
                fullWidth
                data-attr="customize-sidebar-search"
            />
            {!shortcutDataHasLoaded ? (
                <Spinner />
            ) : customizeProductGroups.length === 0 ? (
                <p className="text-xs text-secondary mb-0">No products match your search. Try a different name.</p>
            ) : (
                customizeProductGroups.map((group) => (
                    <section key={group.label} aria-label={group.label} className="flex flex-col gap-1">
                        <h4 className="text-xs font-semibold text-secondary mb-0">{group.label}</h4>
                        <div className="grid gap-1 @md:grid-cols-2">
                            {group.items.map((item) => {
                                const starred = draftStarredPaths.has(item.path)
                                return (
                                    <LemonButton
                                        key={item.path}
                                        type="tertiary"
                                        size="small"
                                        fullWidth
                                        active={starred}
                                        aria-pressed={starred}
                                        icon={
                                            <span className="size-4 flex items-center">
                                                <NavProductIcon item={item} />
                                            </span>
                                        }
                                        sideIcon={
                                            starred ? (
                                                <IconStarFilled className="text-warning" />
                                            ) : (
                                                <IconStar className="text-tertiary" />
                                            )
                                        }
                                        tooltip={<NavProductTooltip item={item} />}
                                        tooltipDocLink={sidebarProductMeta(item).docsHref}
                                        tooltipPlacement="top"
                                        onClick={() => setDraftStarred(item.path, !starred)}
                                        data-attr="configure-starred-app-toggle"
                                    >
                                        <span className="truncate">{productsItemName(item)}</span>
                                    </LemonButton>
                                )
                            })}
                        </div>
                    </section>
                ))
            )}
        </section>
    )
}
