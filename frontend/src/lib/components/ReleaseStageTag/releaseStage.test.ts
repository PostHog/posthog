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

    test.each<[string | null, string | null | undefined, ReleaseStage | null]>([
        ['Pulse', 'Pulse', 'internal'],
        ['Inbox', 'Self-driving inbox', 'beta'],
        ['CustomerAnalytics', 'Customer analytics', 'beta'],
        ['CustomerAnalyticsAccount', 'Acme Inc', null],
        ['Dashboard', 'Dashboard', null],
        ['AIObservability', 'AI observability', null],
        ['AIObservabilityTags', 'Taggers', 'alpha'],
        ['SQLEditor', 'SQL editor', null],
        ['Pulse', undefined, null],
        [null, 'Pulse', null],
    ])('the %s scene titled %s shows %s', (sceneId, title, expected) => {
        const product = releaseStageProductForScene(sceneId, title)
        expect(product ? releaseStage(product) : null).toEqual(expected)
    })
})
