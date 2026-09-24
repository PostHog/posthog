import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardType } from '~/types'

import { textCardModalLogic } from './textCardModalLogic'

const makeDashboard = (body: string = 'existing text', agentContext: string = ''): DashboardType =>
    ({
        id: 123,
        name: 'Test dashboard',
        description: '',
        pinned: false,
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        last_accessed_at: null,
        is_shared: false,
        deleted: false,
        creation_mode: 'default',
        tiles: [
            {
                id: 1,
                color: null,
                layouts: {},
                text: {
                    body,
                    agent_context: agentContext,
                    last_modified_at: '2024-01-01T00:00:00Z',
                },
            },
        ],
        filters: {},
        tags: [],
        user_access_level: AccessControlLevel.Editor,
    }) as DashboardType

describe('textCardModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('does not show toast for expected form validation errors', async () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard('x'.repeat(4001)),
            textTileId: 1,
            onClose: jest.fn(),
            tileType: 'text',
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            textTileValidationErrors: {
                body: 'Text is too long (4000 characters max)',
                agent_context: null,
            },
        })

        logic.actions.submitTextTileFailure({ error: 'Validation failed', errors: {} } as any, {})

        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('rejects empty text card body in form validation', async () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard(''),
            textTileId: null,
            onClose: jest.fn(),
            tileType: 'text',
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            textTileValidationErrors: {
                body: 'This card would be empty! Type something first',
                agent_context: null,
            },
        })

        logic.actions.submitTextTileFailure({ error: 'Validation failed', errors: {} } as any, {})

        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('defaults new image tiles to a transparent background', () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard(),
            textTileId: null,
            onClose: jest.fn(),
            tileType: 'image',
        })
        logic.mount()

        expect(logic.values.textTile.transparent_background).toBe(true)
    })

    it('loads existing agent context', () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard('Dashboard summary', 'Semantic layer metric: activation_rate'),
            textTileId: 1,
            onClose: jest.fn(),
            tileType: 'text',
        })
        logic.mount()

        expect(logic.values.textTile.agent_context).toBe('Semantic layer metric: activation_rate')
    })

    it('does not show toast for expected api body validation errors', () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard('valid'),
            textTileId: 1,
            onClose: jest.fn(),
            tileType: 'text',
        })
        logic.mount()

        logic.actions.submitTextTileFailure(
            {
                error: 'Validation failed',
                errors: {},
            } as any,
            { body: ['Text is too long (4000 characters max)'] }
        )

        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('shows toast for unexpected submit failures', () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard('valid'),
            textTileId: 1,
            onClose: jest.fn(),
            tileType: 'text',
        })
        logic.mount()

        logic.actions.submitTextTileFailure(
            {
                error: 'Network error',
                errors: {},
            } as any,
            {}
        )

        expect(lemonToast.error).toHaveBeenCalledWith('Could not save text: Network error')
    })

    it('uses image wording for unexpected image tile save failures', () => {
        const logic = textCardModalLogic({
            dashboard: makeDashboard('![Image](https://example.com/image.png)'),
            textTileId: 1,
            onClose: jest.fn(),
            tileType: 'image',
        })
        logic.mount()

        logic.actions.submitTextTileFailure(
            {
                error: 'Network error',
                errors: {},
            } as any,
            {}
        )

        expect(lemonToast.error).toHaveBeenCalledWith('Could not save image: Network error')
    })

    it.each([
        ['image', '![Diagram](https://example.com/diagram.png)'],
        ['text', 'Dashboard context'],
    ])('reports %s content type when a text tile saves', (contentType, body) => {
        const agentContext = 'Semantic layer metric: activation_rate'
        const logic = textCardModalLogic({
            dashboard: makeDashboard(),
            textTileId: null,
            onClose: jest.fn(),
            tileType: 'text',
        })
        logic.mount()

        logic.actions.submitTextTileSuccess({
            body,
            agent_context: agentContext,
            transparent_background: false,
        })

        expect(posthog.capture).toHaveBeenCalledWith(
            'dashboard text tile saved',
            expect.objectContaining({
                content_type: contentType,
                has_agent_context: true,
                agent_context_length: agentContext.length,
            })
        )
    })
})
