import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    attachedContextItemKey,
    attachedContextLogic,
    toolStreamEventsLogic,
} from 'products/posthog_ai/frontend/api/logics'
import { foregroundStreamLogic } from 'products/posthog_ai/frontend/logics/foregroundStreamLogic'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/types/streamTypes'

import { buildBIAgentContext } from './biAgentContext'
import { biAgentSyncLogic } from './biAgentSyncLogic'
import { catalogMetricWorksheet } from './biCatalog'
import { biWorksheetsLogic } from './biWorksheetsLogic'

it('dismisses the hidden worksheet draft with its chip, including later draft updates', () => {
    initKeaTests()
    const unmount = attachedContextLogic.mount()
    try {
        const node = catalogMetricWorksheet({
            name: 'revenue',
            definition: { kind: NodeKind.HogQLQuery, query: 'SELECT 42 AS revenue' },
        })!
        const context = buildBIAgentContext(node, 'worksheet-test', 'Local draft title')
        attachedContextLogic.actions.registerContext('bi-test', context)
        expect(attachedContextLogic.values.contextItems.some((item) => item.value?.includes('SELECT 42'))).toBe(true)

        const chip = context.find((item) => item.type === 'insight')!
        attachedContextLogic.actions.dismissContext(attachedContextItemKey(chip), chip.dismissGroup)
        attachedContextLogic.actions.registerContext(
            'bi-test',
            buildBIAgentContext(node, 'worksheet-test', 'Updated draft title')
        )
        expect(
            attachedContextLogic.values.contextItems.filter((item) =>
                ['insight', 'data_catalog_metric', 'text'].includes(item.type)
            )
        ).toEqual([])
    } finally {
        unmount()
    }
})

it('refreshes the worksheet library after a completed foreground tool and unregisters on unmount', () => {
    initKeaTests()
    const library = biWorksheetsLogic()
    const unmountLibrary = library.mount()
    const refresh = jest.spyOn(library.actions, 'loadWorksheets')
    const unmountSync = biAgentSyncLogic.mount()
    const bus = toolStreamEventsLogic.findMounted()
    expect(bus).not.toBeNull()
    const unmountBus = bus!.mount()
    try {
        foregroundStreamLogic.actions.setForegroundStream('worksheet-run', 'worksheet-panel')
        const event: ToolStreamEvent = {
            streamKey: 'worksheet-run',
            toolCallId: 'create-worksheet',
            toolName: 'insight-create',
            rawToolName: 'exec',
            phase: 'completed',
            invocation: {} as ToolStreamEvent['invocation'],
            source: 'live',
        }
        bus!.actions.emitToolEvent({ ...event, phase: 'started' })
        expect(refresh).not.toHaveBeenCalled()
        bus!.actions.emitToolEvent(event)
        expect(refresh).toHaveBeenCalledTimes(1)
        unmountSync()
        bus!.actions.emitToolEvent(event)
        expect(refresh).toHaveBeenCalledTimes(1)
    } finally {
        refresh.mockRestore()
        unmountBus()
        unmountLibrary()
    }
})
