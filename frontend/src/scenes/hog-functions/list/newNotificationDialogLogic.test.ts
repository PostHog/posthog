import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

import { newNotificationDialogLogic, notificationName } from './newNotificationDialogLogic'

describe('newNotificationDialogLogic', () => {
    let logic: ReturnType<typeof newNotificationDialogLogic.build>
    let createSpy: jest.SpyInstance

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/integrations': { count: 0, results: [] },
            },
        })
        initKeaTests()
        jest.spyOn(api.hogFunctions, 'getTemplate').mockResolvedValue({
            id: 'template-slack',
            code: 'print(1)',
            inputs_schema: [],
            icon_url: null,
        } as any)
        createSpy = jest.spyOn(api.hogFunctions, 'create').mockResolvedValue({ id: 'created' } as any)

        logic = newNotificationDialogLogic({
            triggers: [{ subTemplateId: 'mcp-tool-error', label: 'Tool error' }],
            onCreated: () => {},
        })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // A broken MCP tool fails on every call and agents retry in loops, so this destination is only
    // safe to ship deduped. The sub-template declares masking; if creation stops forwarding it the
    // alert silently goes back to one message per event, which is what makes it floodable.
    it('creates the MCP failure alert deduped per failing tool', async () => {
        // Slack rather than a webhook destination: the webhook validator calls URL.canParse, which
        // jsdom doesn't implement, so it throws before the form can submit.
        logic.actions.setNotificationFormValues({
            destination: 'slack',
            slackIntegrationId: 1,
            slackChannel: 'C123|alerts',
        })

        await expectLogic(logic, () => logic.actions.submitNotificationForm()).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledTimes(1)
        const masking = createSpy.mock.calls[0][0].masking
        expect(masking).toMatchObject({ ttl: 30 * 60 })
        // Keyed on the effective tool, so each distinct broken tool still gets through.
        expect(masking.hash).toContain('$mcp_tool_name')
        expect(masking.hash).toContain('$mcp_exec_tool_call_name')
        // The filters only require $mcp_is_error, so an event can arrive with neither tool-name
        // property. HogMaskerService skips masking when the hash evaluates falsy, so the expression
        // has to yield a constant for those rather than an empty string.
        expect(masking.hash).toContain("!= ''")
        expect(masking.hash).toContain('unknown-tool')
    })

    // Falling back to the sub-template's own filters would make the notification fire for every flag
    it('creates a notification bound to one resource, named after it', async () => {
        const boundFilters: CyclotronJobFiltersType = {
            source: 'internal-events',
            events: [{ id: '$activity_log_entry_created', type: 'events' }],
            properties: [
                { key: 'item_id', type: PropertyFilterType.Event, value: ['42'], operator: PropertyOperator.Exact },
            ],
        }
        const boundLogic = newNotificationDialogLogic({
            triggers: [{ subTemplateId: 'feature-flag-change', label: 'Flag changed', filters: boundFilters }],
            onCreated: () => {},
            scopeLabel: 'checkout-redesign',
        })
        boundLogic.mount()

        try {
            boundLogic.actions.setNotificationFormValues({
                destination: 'slack',
                slackIntegrationId: 1,
                slackChannel: 'C123|releases',
            })

            await expectLogic(boundLogic, () => boundLogic.actions.submitNotificationForm()).toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledTimes(1)
            expect(createSpy.mock.calls[0][0]).toMatchObject({
                type: 'internal_destination',
                name: 'Notify Slack for feature flag changes (checkout-redesign)',
                filters: boundFilters,
            })
        } finally {
            boundLogic.unmount()
        }
    })

    // The chosen trigger, not the first one, decides the sub-template
    it('creates the notification for the chosen trigger', async () => {
        const staleFilters: CyclotronJobFiltersType = {
            source: 'internal-events',
            events: [{ id: '$feature_flag_stale', type: 'events' }],
            properties: [
                { key: 'flag_id', type: PropertyFilterType.Event, value: ['42'], operator: PropertyOperator.Exact },
            ],
        }
        const multiLogic = newNotificationDialogLogic({
            triggers: [
                { subTemplateId: 'feature-flag-change', label: 'Flag changed' },
                { subTemplateId: 'feature-flag-stale', label: 'Flag became stale', filters: staleFilters },
            ],
            onCreated: () => {},
        })
        multiLogic.mount()

        try {
            multiLogic.actions.setNotificationFormValues({
                trigger: 'feature-flag-stale',
                destination: 'slack',
                slackIntegrationId: 1,
                slackChannel: 'C123|releases',
            })

            await expectLogic(multiLogic, () => multiLogic.actions.submitNotificationForm()).toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledTimes(1)
            expect(createSpy.mock.calls[0][0]).toMatchObject({
                name: 'Notify Slack when a feature flag becomes stale',
                filters: staleFilters,
            })
        } finally {
            multiLogic.unmount()
        }
    })
    
    it('keeps a scoped name within the name column limit', () => {
        const name = notificationName('Notify Slack for feature flag changes', 'k'.repeat(400))

        expect(name.length).toBeLessThanOrEqual(400)
        expect(name.startsWith('Notify Slack for feature flag changes (k')).toBe(true)
        expect(name.endsWith('…)')).toBe(true)
        expect(notificationName('Notify Slack', 'checkout')).toBe('Notify Slack (checkout)')
    })
})
