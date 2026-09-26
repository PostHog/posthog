import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { cn } from 'lib/utils/css-classes'

import { ProjectTree } from '../../ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { CustomizeSidebarModal } from './CustomizeSidebarModal'
import { NavProductRow } from './NavProductRow'
import { PRODUCTS_STARRED_TREE_KEY, navProductsTabLogic } from './navProductsTabLogic'

export function NavTabProducts(): JSX.Element {
    const { pinnedItems, groupedItems, allProductsVisible, allProductsCollapsible } = useValues(navProductsTabLogic)
    const { setAllProductsOpen } = useActions(navProductsTabLogic)
    // Fade only on a toggle the user makes, not on the first render after starred items load. A height
    // slide over the whole product list moves too far to read, so the panel opens in place.
    const [animatePanel, setAnimatePanel] = useState(false)
    const { shortcutDataHasLoaded } = useValues(projectTreeDataLogic)
    const { fullFileSystemFiltered: starredProducts } = useValues(
        projectTreeLogic({ key: PRODUCTS_STARRED_TREE_KEY, root: 'shortcuts://', shortcutScope: 'products' })
    )
    const showStarred = shortcutDataHasLoaded && starredProducts.length > 0

    return (
        <div className="flex flex-col h-full min-h-0 group/colorful-product-icons colorful-product-icons-true">
            {/* Parents own the spacing: this gap separates the sections, and each section's gap separates
                its title from its rows. Titles and rows carry no vertical padding or margin. */}
            <ScrollableShadows
                direction="vertical"
                className="flex-1 min-h-0"
                innerClassName="px-1 pb-2"
                contentClassName="flex flex-col gap-3"
                styledScrollbars
            >
                {pinnedItems.length > 0 && (
                    <div className="flex flex-col gap-px">
                        {pinnedItems.map((item) => (
                            <NavProductRow key={`${item.path}-${item.href}`} item={item} pinned />
                        ))}
                    </div>
                )}
                {showStarred && (
                    <section aria-label="Starred" className="flex flex-col gap-0.5">
                        <h3 className="px-2 mb-0 text-xs leading-4 font-semibold text-tertiary">Starred</h3>
                        {/* The tree insets its rows by 5px and pads itself by 4px vertically. This lines its
                            icons up with the rows above and cancels its own vertical padding. */}
                        <div className="-ml-[5px] -my-1">
                            <ProjectTree
                                root="shortcuts://"
                                shortcutScope="products"
                                logicKey={PRODUCTS_STARRED_TREE_KEY}
                                onlyTree
                                showShortcutHelp={false}
                            />
                        </div>
                    </section>
                )}
                {groupedItems.length > 0 ? (
                    <Collapsible
                        open={allProductsVisible}
                        onOpenChange={(open) => {
                            setAnimatePanel(true)
                            setAllProductsOpen(open)
                        }}
                        className="flex flex-col gap-2"
                    >
                        {allProductsCollapsible && (
                            <Collapsible.Trigger
                                className="min-h-6 py-0.5 rounded hover:bg-fill-button-tertiary-hover focus-visible:bg-fill-button-tertiary-hover pr-2"
                                labelClassName="flex-1 text-xs font-semibold text-tertiary normal-case tracking-normal"
                                data-attr="nav-apps-project-toggle"
                            >
                                {allProductsVisible ? 'All products' : 'See all products'}
                            </Collapsible.Trigger>
                        )}
                        <Collapsible.Panel
                            className={cn(
                                'gap-3 transition-opacity duration-150 ease-out data-[starting-style]:opacity-0 data-[ending-style]:opacity-0',
                                !animatePanel && 'transition-none',
                                'motion-reduce:transition-none'
                            )}
                        >
                            {groupedItems.map((group) => (
                                <section key={group.label} aria-label={group.label} className="flex flex-col gap-0.5">
                                    <h3 className="px-2 mb-0 text-xs leading-4 font-semibold text-secondary">
                                        {group.label}
                                    </h3>
                                    <div className="flex flex-col gap-px">
                                        {group.items.map((item) => (
                                            <NavProductRow key={`${item.path}-${item.href}`} item={item} />
                                        ))}
                                    </div>
                                </section>
                            ))}
                        </Collapsible.Panel>
                    </Collapsible>
                ) : (
                    pinnedItems.length === 0 &&
                    !showStarred && (
                        <p className="px-2 mb-0 text-xs text-tertiary">No products found. Try a different search.</p>
                    )
                )}
            </ScrollableShadows>
            <CustomizeSidebarModal />
        </div>
    )
}
