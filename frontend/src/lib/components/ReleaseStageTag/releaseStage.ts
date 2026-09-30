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

/** The product that owns a scene, when that product has a release stage to show in the scene title. */
export function releaseStageProductForScene(sceneId: string | null): FileSystemImport | undefined {
    if (!sceneId) {
        return undefined
    }
    return getTreeItemsProducts().find(
        (product) =>
            (product.sceneKey === sceneId || product.sceneKeys?.includes(sceneId)) && releaseStage(product) !== null
    )
}
