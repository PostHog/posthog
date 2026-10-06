import { productsItemName } from '~/layout/panel-layout/navbar/tabs/productsCatalog'
import { getTreeItemsProducts } from '~/products'
import { FileSystemImport, ProductItemCategory } from '~/queries/schema/schema-general'

export type ReleaseStage = 'alpha' | 'beta' | 'internal'

export type ReleaseStageProduct = Pick<FileSystemImport, 'category' | 'tags' | 'flag'>

export function releaseStage(product: ReleaseStageProduct): ReleaseStage | null {
    if (product.category === ProductItemCategory.UNRELEASED) {
        return 'internal'
    }
    return product.tags?.[0] ?? null
}

/**
 * The product that owns a scene, when that product has a release stage to show in the scene title.
 * The title must be the product name, so a record title (such as a customer name) does not get the tag.
 */
export function releaseStageProductForScene(
    sceneId: string | null,
    title: string | null | undefined
): FileSystemImport | undefined {
    if (!sceneId || !title) {
        return undefined
    }
    const products = getTreeItemsProducts()
    const owners = products.filter((product) => product.sceneKey === sceneId)
    // Many products list scenes they do not own in `sceneKeys`, so a scene listed by more than one has no clear owner.
    const candidates = owners.length > 0 ? owners : products.filter((product) => product.sceneKeys?.includes(sceneId))
    const [product] = candidates
    return candidates.length === 1 && releaseStage(product) !== null && productsItemName(product) === title
        ? product
        : undefined
}
