import {
    asInsightSceneSource,
    insightShortIdForEntry,
    withInsightSceneSource,
    withSceneSource,
} from './insightNavigation'

describe('insightNavigation', () => {
    it('keeps existing search params when tagging a source', () => {
        expect(withSceneSource('/insights/abc123?dashboard=1', 'starred')).toEqual(
            '/insights/abc123?dashboard=1#sceneSource=starred'
        )
    })

    it.each([
        ['insight', '/insights/abc123#sceneSource=recents'],
        ['insight/funnels', '/insights/abc123#sceneSource=recents'],
        ['dashboard', '/insights/abc123'],
    ])('tags a %s entry', (type, expected) => {
        expect(withInsightSceneSource('/insights/abc123', type, 'recents')).toEqual(expected)
    })

    it.each([
        ['starred', 'starred'],
        ['whatever-someone-typed', null],
        ['toString', null],
        [undefined, null],
    ])('keeps %s out of analytics unless it is a source we defined', (value, expected) => {
        expect(asInsightSceneSource(value)).toEqual(expected)
    })

    it.each([
        ['insight/funnels', 'abc123', 'abc123'],
        ['dashboard', 'abc123', undefined],
        ['insight', undefined, undefined],
    ])('reads the short ID of a %s entry', (type, ref, expected) => {
        expect(insightShortIdForEntry(type, ref)).toEqual(expected)
    })
})
