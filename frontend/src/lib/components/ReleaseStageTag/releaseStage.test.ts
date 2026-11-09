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

    test.each<[string | null, string | null | undefined, ReleaseStage | null, boolean]>([
        ['Pulse', 'Pulse', 'internal', false],
        ['Inbox', 'Self-driving inbox', 'beta', false],
        ['Inbox', 'Self-driving inbox', null, true],
        ['CustomerAnalytics', 'Customer analytics', 'beta', false],
        ['CustomerAnalytics', 'Customer analytics', 'beta', true],
        ['CustomerAnalyticsAccount', 'Acme Inc', null, false],
        ['Dashboard', 'Dashboard', null, false],
        ['AIObservability', 'AI observability', null, false],
        ['AIObservabilityTags', 'Taggers', 'alpha', false],
        ['SQLEditor', 'SQL editor', null, false],
        ['Pulse', undefined, null, false],
        [null, 'Pulse', null, false],
    ])('the %s scene titled %s shows %s with usage display %s', (sceneId, title, expected, selfDrivingUsageDisplay) => {
        const product = releaseStageProductForScene(sceneId, title)
        expect(product ? releaseStage(product, selfDrivingUsageDisplay) : null).toEqual(expected)
    })
})
