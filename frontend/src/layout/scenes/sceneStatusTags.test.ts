import { getSceneStatusTag } from './sceneStatusTags'

jest.mock('~/products', () => ({
    getTreeItemsProducts: () => [
        // Multi-scene product: every scene key in the list inherits the tag
        { tags: ['beta'], sceneKey: 'Alpha', sceneKeys: ['Alpha', 'AlphaChild'] },
        // Falls back to the single sceneKey when sceneKeys is absent
        { tags: ['alpha'], sceneKey: 'Solo' },
        // Untagged product contributes nothing
        { sceneKey: 'Stable', sceneKeys: ['Stable'] },
    ],
}))

describe('getSceneStatusTag', () => {
    it.each([
        ['Alpha', 'beta'],
        ['AlphaChild', 'beta'],
        ['Solo', 'alpha'],
        ['Inbox', 'beta'], // special navbar entry not in the product tree
    ])('maps %s to %s', (sceneId, expected) => {
        expect(getSceneStatusTag(sceneId)).toBe(expected)
    })

    it.each([['Stable'], ['UnknownScene'], [null], [undefined]])('returns null for %s', (sceneId) => {
        expect(getSceneStatusTag(sceneId)).toBeNull()
    })
})
