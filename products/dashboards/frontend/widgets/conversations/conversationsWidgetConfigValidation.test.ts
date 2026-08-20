import { patchConversationsWidgetFilterFields } from './conversationsWidgetConfigValidation'

describe('conversationsWidgetConfigValidation', () => {
    it('sets and clears a saved view without dropping other config', () => {
        const config = { limit: 15, status: 'open' as const, priorities: ['high' as const] }
        const withSavedView = patchConversationsWidgetFilterFields(config, { savedViewId: 'view-1' })

        expect(withSavedView).toMatchObject({
            limit: 15,
            status: 'open',
            priorities: ['high'],
            savedViewId: 'view-1',
        })

        const cleared = patchConversationsWidgetFilterFields(withSavedView, { savedViewId: null })
        expect(cleared.savedViewId).toBeNull()
        expect(cleared.limit).toBe(15)
    })

    it('rejects saved view IDs longer than the backend short ID limit', () => {
        expect(() => patchConversationsWidgetFilterFields({}, { savedViewId: '1234567890123' })).toThrow()
    })
})
