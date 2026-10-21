import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { newNotificationDialogLogic } from './newNotificationDialogLogic'

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

        logic = newNotificationDialogLogic({ subTemplateId: 'mcp-tool-error', onCreated: () => {} })
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

    it.each([
        ['mcp-tool-error', ['slack', 'discord', 'microsoft-teams', 'webhook', 'github']],
        ['data-warehouse-sync-failed', ['slack', 'discord', 'microsoft-teams', 'webhook']],
        ['pa-rageclick', ['slack', 'discord', 'microsoft-teams', 'webhook']],
    ] as const)('offers the destinations %s ships a variant for', (subTemplateId, expectedDestinations) => {
        const subTemplateLogic = newNotificationDialogLogic({ subTemplateId, onCreated: () => {} })
        subTemplateLogic.mount()

        expect(subTemplateLogic.values.destinationOptions.map((option) => option.value)).toEqual(expectedDestinations)

        subTemplateLogic.unmount()
    })

    it.each([
        ['no installation', { githubIntegrationId: null, githubRepository: null }],
        ['no repository', { githubIntegrationId: 7, githubRepository: null }],
    ])('asks for a GitHub %s without asking for a webhook URL', async (_name, github) => {
        logic.actions.setNotificationFormValues({ destination: 'github', ...github })

        await expectLogic(logic, () => logic.actions.submitNotificationForm()).toFinishAllListeners()

        expect(createSpy).not.toHaveBeenCalled()
        expect(
            Object.keys(logic.values.notificationFormErrors).filter(
                (key) => (logic.values.notificationFormErrors as any)[key]
            )
        ).toEqual(github.githubIntegrationId ? ['githubRepository'] : ['githubIntegrationId', 'githubRepository'])
    })

    it('opens a GitHub issue for the failing tool, at most one per day', async () => {
        logic.actions.setNotificationFormValues({
            destination: 'github',
            githubIntegrationId: 7,
            githubRepository: 'mcp-server',
        })

        await expectLogic(logic, () => logic.actions.submitNotificationForm()).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledTimes(1)
        const payload = createSpy.mock.calls[0][0]
        expect(payload.template_id).toBe('template-github')
        expect(payload.inputs.github_installation).toEqual({ value: 7 })
        expect(payload.inputs.repository).toEqual({ value: 'mcp-server' })
        expect(payload.inputs.posthog_issue_id).toEqual({ value: '{event.uuid}' })
        expect(payload.inputs.posthog_issue_url.value).toContain('/mcp-analytics/tool-quality')
        expect(payload.masking.ttl).toBe(86400)
        expect(payload.masking.hash).toMatch(/^\{substring\(md5Hex\(.*\), 1, 1\)\}$/s)
    })
})
