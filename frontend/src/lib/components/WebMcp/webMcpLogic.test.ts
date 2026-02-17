import { FEATURE_FLAGS } from 'lib/constants'

import { initKeaTests } from '~/test/init'

import { webMcpLogic } from './webMcpLogic'
import { buildWebMcpTools } from './webMcpToolkit'

describe('webMcpLogic', () => {
    let mockRegisterTool: jest.Mock
    let mockUnregister: jest.Mock

    beforeEach(() => {
        mockUnregister = jest.fn()
        mockRegisterTool = jest.fn(() => ({ unregister: mockUnregister }))
        initKeaTests()
    })

    afterEach(() => {
        delete (navigator as any).modelContext
    })

    function setupModelContext(): void {
        Object.defineProperty(navigator, 'modelContext', {
            value: { registerTool: mockRegisterTool },
            configurable: true,
        })
    }

    function mountWithFlag(enabled: boolean): ReturnType<typeof webMcpLogic.build> {
        const logic = webMcpLogic()

        // Patch featureFlags value before mount
        const featureFlagLogic = require('lib/logic/featureFlagLogic').featureFlagLogic
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_MCP], { [FEATURE_FLAGS.WEB_MCP]: enabled })

        logic.mount()
        return logic
    }

    it('registers tools when feature flag is enabled and navigator.modelContext exists', () => {
        setupModelContext()
        const logic = mountWithFlag(true)

        const expectedToolCount = buildWebMcpTools().length
        expect(mockRegisterTool).toHaveBeenCalledTimes(expectedToolCount)
        expect(expectedToolCount).toBeGreaterThan(0)

        // Each call should provide a tool with name, description, inputSchema, execute
        const firstCall = mockRegisterTool.mock.calls[0][0]
        expect(firstCall).toHaveProperty('name')
        expect(firstCall).toHaveProperty('description')
        expect(firstCall).toHaveProperty('inputSchema')
        expect(firstCall).toHaveProperty('execute')

        logic.unmount()
    })

    it('does not register tools when feature flag is disabled', () => {
        setupModelContext()
        const logic = mountWithFlag(false)

        expect(mockRegisterTool).not.toHaveBeenCalled()

        logic.unmount()
    })

    it('does not register tools when navigator.modelContext is unavailable', () => {
        const logic = mountWithFlag(true)

        expect(mockRegisterTool).not.toHaveBeenCalled()

        logic.unmount()
    })

    it('unregisters all tools on unmount', () => {
        setupModelContext()
        const logic = mountWithFlag(true)

        const registrationCount = mockRegisterTool.mock.calls.length
        expect(registrationCount).toBeGreaterThan(0)

        logic.unmount()

        expect(mockUnregister).toHaveBeenCalledTimes(registrationCount)
    })
})

describe('buildWebMcpTools', () => {
    it('returns tools with valid structure', () => {
        const tools = buildWebMcpTools()

        expect(tools.length).toBeGreaterThan(0)

        for (const tool of tools) {
            expect(tool.name).toMatch(/^posthog:/)
            expect(tool.description).toBeTruthy()
            expect(tool.inputSchema).toHaveProperty('type', 'object')
            expect(typeof tool.execute).toBe('function')
        }
    })

    it('includes expected core tools', () => {
        const tools = buildWebMcpTools()
        const names = tools.map((t) => t.name)

        expect(names).toContain('posthog:dashboards-get-all')
        expect(names).toContain('posthog:dashboard-get')
        expect(names).toContain('posthog:feature-flags-get-all')
        expect(names).toContain('posthog:insights-get-all')
        expect(names).toContain('posthog:entity-search')
    })

    it('marks all tools as read-only', () => {
        const tools = buildWebMcpTools()
        for (const tool of tools) {
            expect(tool.annotations?.readOnly).toBe(true)
        }
    })

    it('has unique tool names', () => {
        const tools = buildWebMcpTools()
        const names = tools.map((t) => t.name)
        expect(new Set(names).size).toBe(names.length)
    })
})
