import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { foregroundStreamLogic, toolStreamEventsLogic } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/api/types'

import { certificationsLogic } from './certificationsLogic'
import {
    CERTIFICATION_TOOLS,
    dataCatalogAgentSyncLogic,
    METRIC_TOOLS,
    READ_TOOLS,
    RELATIONSHIP_TOOLS,
} from './dataCatalogAgentSyncLogic'
import { DATA_CATALOG_MCP_TOOLS } from './generated/agentContext'

// The reload targets are stubs here: this file covers which reloads the sync logic asks for, not
// what the catalog logics do with them.
jest.mock('./certificationsLogic', () => ({
    certificationsLogic: {
        isMounted: () => true,
        actions: { loadCertifications: jest.fn(), loadDatabase: jest.fn() },
    },
}))

function toolEvent({
    toolName,
    streamKey = 'run-1',
    phase = 'completed',
    source = 'live',
}: Partial<ToolStreamEvent> & Pick<ToolStreamEvent, 'toolName'>): ToolStreamEvent {
    return {
        streamKey,
        toolCallId: 'tool-call-1',
        toolName,
        rawToolName: 'exec',
        phase,
        invocation: {
            rawServerName: 'posthog',
            rawToolName: 'exec',
            input: { command: `call ${toolName} {"name":"weekly_active_users"}` },
        } as unknown as ToolStreamEvent['invocation'],
        source,
    }
}

describe('dataCatalogAgentSyncLogic', () => {
    let logic: ReturnType<typeof dataCatalogAgentSyncLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = dataCatalogAgentSyncLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('routes completed writes from the foreground run', async () => {
        foregroundStreamLogic.actions.setForegroundStream('run-1', 'panel-1')

        toolStreamEventsLogic.actions.emitToolEvent(toolEvent({ toolName: 'data-catalog-metric-create' }))

        await expectLogic(logic).toDispatchActions(['toolCompleted', 'metricsChanged']).toFinishAllListeners()
    })

    it.each([
        ['a replayed tool call', { source: 'replay' as const }],
        ['a background run', { streamKey: 'run-2' }],
    ])('does not react to %s', async (_label, eventOverrides) => {
        foregroundStreamLogic.actions.setForegroundStream('run-1', 'panel-1')

        toolStreamEventsLogic.actions.emitToolEvent(
            toolEvent({ toolName: 'data-catalog-metric-create', ...eventOverrides })
        )

        await expectLogic(logic).toNotHaveDispatchedActions(['toolCompleted']).toFinishAllListeners()
    })

    it('does not reload for an incomplete tool call', async () => {
        foregroundStreamLogic.actions.setForegroundStream('run-1', 'panel-1')

        toolStreamEventsLogic.actions.emitToolEvent(
            toolEvent({ toolName: 'data-catalog-metric-create', phase: 'started' })
        )

        await expectLogic(logic).toDispatchActions(['toolCompleted']).toNotHaveDispatchedActions(['metricsChanged'])
    })

    it('does not reload an open metric after a read-only metric run', async () => {
        foregroundStreamLogic.actions.setForegroundStream('run-1', 'panel-1')
        logic.actions.setOpenMetricName('weekly_active_users')

        toolStreamEventsLogic.actions.emitToolEvent(toolEvent({ toolName: 'data-catalog-metric-run' }))

        await expectLogic(logic).toNotHaveDispatchedActions(['toolCompleted']).toFinishAllListeners()
    })

    it('keeps the database reload when a second certification write coalesces with it', async () => {
        foregroundStreamLogic.actions.setForegroundStream('run-1', 'panel-1')

        // Certifying reloads the database view; proposing does not. Both land inside the debounce
        // window, so the surviving dispatch must still carry the reload the first one needs.
        toolStreamEventsLogic.actions.emitToolEvent(
            toolEvent({ toolName: 'data-catalog-certification-certify-execute' })
        )
        toolStreamEventsLogic.actions.emitToolEvent(toolEvent({ toolName: 'data-catalog-certification-propose' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(certificationsLogic.actions.loadDatabase).toHaveBeenCalledWith({ force: true })
    })

    it('does not reload the database when only proposals land', async () => {
        foregroundStreamLogic.actions.setForegroundStream('run-1', 'panel-1')

        toolStreamEventsLogic.actions.emitToolEvent(toolEvent({ toolName: 'data-catalog-certification-propose' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(certificationsLogic.actions.loadCertifications).toHaveBeenCalled()
        expect(certificationsLogic.actions.loadDatabase).not.toHaveBeenCalled()
    })

    it('classifies every generated tool that can mutate or read a metric result', () => {
        const routedTools = [...METRIC_TOOLS, ...RELATIONSHIP_TOOLS, ...CERTIFICATION_TOOLS, ...READ_TOOLS]
        const generatedTools = DATA_CATALOG_MCP_TOOLS.map((tool) => tool.name).filter(
            (toolName) => !toolName.endsWith('-prepare')
        )

        expect(new Set(routedTools)).toEqual(new Set(generatedTools))
    })
})
