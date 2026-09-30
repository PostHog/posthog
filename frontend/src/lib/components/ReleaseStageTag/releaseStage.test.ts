import { ProductItemCategory } from '~/queries/schema/schema-general'

import { ReleaseStage, ReleaseStageProduct, releaseStage, releaseStageProductForScene } from './releaseStage'

describe('releaseStage', () => {
    test.each<[string, ReleaseStageProduct, ReleaseStage | null]>([
        ['released product', { category: ProductItemCategory.ANALYTICS }, null],
        ['alpha product', { category: ProductItemCategory.ANALYTICS, tags: ['alpha'] }, 'alpha'],
        ['beta product', { category: ProductItemCategory.ANALYTICS, tags: ['beta'] }, 'beta'],
        ['unreleased product', { category: ProductItemCategory.UNRELEASED }, 'internal'],
        ['unreleased product tagged alpha', { category: ProductItemCategory.UNRELEASED, tags: ['alpha'] }, 'internal'],
    ])('%s', (_, product, expected) => {
        expect(releaseStage(product)).toEqual(expected)
    })

    test.each<[string | null, ReleaseStage | null]>([
        ['Links', 'internal'],
        ['DataCatalog', 'beta'],
        ['Inbox', 'beta'],
        ['Dashboard', null],
        ['AIObservability', null],
        ['AIObservabilityTags', 'alpha'],
        ['SQLEditor', null],
        [null, null],
    ])('the %s scene shows %s', (sceneId, expected) => {
        const product = releaseStageProductForScene(sceneId)
        expect(product ? releaseStage(product) : null).toEqual(expected)
    })
})
