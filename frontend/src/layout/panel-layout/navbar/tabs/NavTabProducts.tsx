import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import { ProjectTree } from '../../ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { ConfigureStarredModal } from './ConfigureStarredModal'
import { NavProductRow } from './NavProductRow'
import { NavProductsMenu } from './NavProductsMenu'
import { PRODUCTS_STARRED_TREE_KEY, navProductsTabLogic } from './navProductsTabLogic'
import { NavTabSection } from './NavTabSection'

export function NavTabProducts(): JSX.Element {
    const { search, groupedItems } = useValues(navProductsTabLogic)
    const { shortcutDataHasLoaded } = useValues(projectTreeDataLogic)
    const { fullFileSystemFiltered: starredProducts } = useValues(
        projectTreeLogic({ key: PRODUCTS_STARRED_TREE_KEY, root: 'shortcuts://', shortcutScope: 'products' })
    )

    return (
        <div className="flex flex-col h-full min-h-0 group/colorful-product-icons colorful-product-icons-true">
            <ScrollableShadows
                direction="vertical"
                className="flex-1 min-h-0"
                innerClassName="px-1 pb-2"
                styledScrollbars
            >
                {(!search.trim() || !shortcutDataHasLoaded || starredProducts.length > 0) && (
                    <NavTabSection
                        label="Starred"
                        dataAttr="nav-apps-starred-toggle"
                        key={`starred-${!!search.trim()}`}
                        actions={<NavProductsMenu />}
                    >
                        {!shortcutDataHasLoaded ? (
                            <Spinner className="m-2" />
                        ) : starredProducts.length > 0 ? (
                            <ProjectTree
                                root="shortcuts://"
                                shortcutScope="products"
                                logicKey={PRODUCTS_STARRED_TREE_KEY}
                                onlyTree
                                showShortcutHelp={false}
                            />
                        ) : (
                            <p className="text-xs text-tertiary px-2 py-1 mb-0">Star products to keep them here.</p>
                        )}
                    </NavTabSection>
                )}
                <NavTabSection
                    label="Project"
                    collapsedLabel="All products"
                    dataAttr="nav-apps-project-toggle"
                    key={`project-${!!search.trim()}`}
                >
                    {groupedItems.map((group) => (
                        <section key={group.label} aria-label={group.label}>
                            {group.label !== 'Project' && (
                                <h3 className="px-2 pt-3 pb-1 mb-0 text-xs font-semibold text-secondary">
                                    {group.label}
                                </h3>
                            )}
                            <div className="flex flex-col gap-px">
                                {group.items.map((item) => (
                                    <NavProductRow key={`${item.path}-${item.href}`} item={item} />
                                ))}
                            </div>
                        </section>
                    ))}
                    {groupedItems.length === 0 && (
                        <p className="text-xs text-tertiary px-2 py-2">No products found. Try a different search.</p>
                    )}
                </NavTabSection>
            </ScrollableShadows>
            <ConfigureStarredModal />
        </div>
    )
}
