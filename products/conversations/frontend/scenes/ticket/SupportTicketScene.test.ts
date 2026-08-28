import { scene } from './SupportTicketScene'

describe('SupportTicketScene paramsToProps', () => {
    // supportTicketSceneLogic is keyed via `key((props) => props.id)`. App.tsx binds the scene's
    // logic (and the side panel context selector reads it) using whatever `paramsToProps` returns,
    // while the rendered component separately builds `supportTicketSceneLogic({ id: ticketId })`.
    // If `paramsToProps` ever stops returning `id` matching that same value, those become two
    // different logic instances: the bound one stays empty, and the ticket detail side panel's
    // access control tab silently disappears (the reported regression this test guards).
    it('keys paramsToProps by id, matching the value the component builds its logic with', () => {
        const props = scene.paramsToProps?.({ params: { ticketId: 'ticket-123' }, searchParams: {}, hashParams: {} })
        expect(props).toEqual(expect.objectContaining({ id: 'ticket-123' }))
    })

    it('falls back to the "new" ticket key when no ticketId param is present', () => {
        const props = scene.paramsToProps?.({ params: {}, searchParams: {}, hashParams: {} })
        expect(props).toEqual(expect.objectContaining({ id: 'new' }))
    })
})
