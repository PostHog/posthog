import { appScenes } from 'scenes/appScenes'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { ITEM_PEEK_SCENES } from './itemPeekScenes'
import { resolveItemPeek } from './resolveItemPeek'

describe('resolveItemPeek', () => {
    test.each([
        [`/project/1${urls.featureFlag(12)}`, 'FeatureFlag', { id: '12' }],
        [`${urls.featureFlag(12)}?tab=usage`, 'FeatureFlag', { id: '12' }],
        [
            urls.dataWarehouseSourceSchema('src', 'sch'),
            'DataWarehouseSourceSchema',
            { sourceId: 'src', schemaId: 'sch' },
        ],
        [urls.insightView('abc123' as InsightShortId), 'Insight', { shortId: 'abc123' }],
        ['/person/some-distinct-id', 'Person', { _: 'some-distinct-id' }],
    ])('peeks %s in %s', (href, sceneId, params) => {
        expect(resolveItemPeek(href)).toMatchObject({ sceneId, sceneParams: { params } })
    })

    test.each([
        ['a list page', urls.featureFlags()],
        ['a create page', urls.featureFlag('new')],
        ['an edit page', urls.insightEdit('abc123' as InsightShortId)],
        ['a sharing page', urls.dashboardSharing(5)],
        ['a settings page', '/settings/project'],
        ['an unknown path', '/not-a-route/12'],
    ])('navigates %s as usual', (_, href) => {
        expect(resolveItemPeek(href)).toBeNull()
    })

    test('every peekable scene is a scene the app can load', () => {
        expect(Object.keys(ITEM_PEEK_SCENES).filter((sceneId) => !(sceneId in appScenes))).toEqual([])
    })
})
