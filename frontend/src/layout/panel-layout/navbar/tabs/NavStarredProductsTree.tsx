import { LemonTreeSize } from 'lib/lemon-ui/LemonTree/LemonTree'

import { getSidebarProduct } from '../../ProjectTree/defaultTree'
import { ProjectTree } from '../../ProjectTree/ProjectTree'
import { sidebarProductMeta } from '../../sidebarProductMeta'
import { PRODUCTS_STARRED_TREE_KEY } from './navProductsTabLogic'
import { NavProductTooltip } from './NavProductTooltip'

export function NavStarredProductsTree({ treeSize = 'default' }: { treeSize?: LemonTreeSize }): JSX.Element {
    return (
        <ProjectTree
            root="shortcuts://"
            shortcutScope="products"
            logicKey={PRODUCTS_STARRED_TREE_KEY}
            onlyTree
            showShortcutHelp={false}
            treeSize={treeSize}
            renderItemTooltip={(treeItem) => {
                const product = getSidebarProduct(treeItem.record?.href)
                return product ? <NavProductTooltip item={product} /> : undefined
            }}
            renderItemTooltipDocLink={(treeItem) => {
                const product = getSidebarProduct(treeItem.record?.href)
                return product ? sidebarProductMeta(product).docsHref : undefined
            }}
        />
    )
}
