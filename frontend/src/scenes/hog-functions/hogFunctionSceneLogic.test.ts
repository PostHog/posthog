import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { Breadcrumb, HogFunctionTemplateType, HogFunctionType } from '~/types'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    hogFunctions: {
        get: jest.fn(),
        getTemplate: jest.fn(),
        update: jest.fn(),
        create: jest.fn(),
    },
}))

const mockApi = api.hogFunctions as jest.Mocked<typeof api.hogFunctions>

const LOG_TRANSFORMATION: HogFunctionType = {
    id: 'fn-1',
    type: 'transformation_log',
    name: 'Scrub PII',
    description: '',
    created_at: '2026-01-01',
    created_by: null,
    updated_at: '2026-01-01',
    enabled: true,
    hog: 'return record',
    inputs_schema: [],
    inputs: {},
    filters: null,
    icon_url: null,
    template: null,
    status: { state: 1, tokens: 0 } as any,
} as unknown as HogFunctionType

const SLACK_TEMPLATE = {
    id: 'template-slack',
    type: 'destination',
    name: 'Slack',
    status: 'stable',
    free: true,
    code: 'return event',
    code_language: 'hog',
    inputs_schema: [],
} as unknown as HogFunctionTemplateType

const makeNotification = (eventId: string, alertId?: string): HogFunctionType =>
    ({
        ...LOG_TRANSFORMATION,
        type: 'internal_destination',
        name: 'Slack notification',
        filters: {
            events: [{ id: eventId, type: 'events' }],
            properties: alertId ? [{ key: 'alert_id', value: alertId, operator: 'exact', type: 'event' }] : [],
        },
    }) as unknown as HogFunctionType

describe('hogFunctionSceneLogic', () => {
    it.each([
        ['an insight alert', makeNotification('$insight_alert_firing', 'alert-1'), ['Insight', 'Alert']],
        ['a logs alert', makeNotification('$logs_alert_firing', 'alert-2'), ['Logs', 'Alert']],
        ['a notification with no owning alert', makeNotification('$health_alert_firing'), ['Notifications']],
    ])('links the breadcrumbs of %s to the product that owns it', async (_, hogFunction, expectedNames) => {
        initKeaTests()
        const { hogFunctionSceneLogic } = require('./HogFunctionScene')
        mockApi.get.mockResolvedValue(hogFunction)

        router.actions.push(urls.hogFunction('fn-1'))
        const logic = hogFunctionSceneLogic({ id: 'fn-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHogFunctionSuccess'])

        const crumbs = logic.values.breadcrumbs.slice(0, -1)
        expect(crumbs.map((crumb: Breadcrumb) => crumb.name)).toEqual(expectedNames)
        expect(crumbs.filter((crumb: Breadcrumb) => !crumb.path)).toEqual([])
        logic.unmount()
    })

    it('falls back from a deep-linked tab the loaded type never renders', async () => {
        // `type` arrives after the URL fires, so ?tab=invocations on a log
        // transformation used to stick and LemonTabs rendered no active content.
        initKeaTests()
        // Required lazily: the scene's component import chain reads the app context
        // at module scope, which initKeaTests only provides at test time.
        const { hogFunctionSceneLogic } = require('./HogFunctionScene')
        mockApi.get.mockResolvedValue(LOG_TRANSFORMATION)

        router.actions.push(urls.hogFunction('fn-1'), { tab: 'invocations' })
        const logic = hogFunctionSceneLogic({ id: 'fn-1' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadHogFunctionSuccess'])
        expect(logic.values.currentTab).toBe('configuration')
    })

    it.each([
        [
            'a messaging template',
            { templateId: 'template-slack' },
            true,
            urls.workflowNewFromDestination('template-slack'),
        ],
        [
            'an alert sub-template of a messaging template',
            { templateId: 'template-slack', subTemplateId: 'insight-alert-firing' as const },
            true,
            urls.hogFunctionNew('template-slack'),
        ],
        [
            'a messaging template while the flag is off',
            { templateId: 'template-slack' },
            false,
            urls.hogFunctionNew('template-slack'),
        ],
        ['a non-messaging template', { templateId: 'template-webhook' }, true, urls.hogFunctionNew('template-webhook')],
    ])('opening the new destination form for %s', (_, props, flagOn, expectedPath) => {
        initKeaTests()
        const { hogFunctionSceneLogic } = require('./HogFunctionScene')
        mockApi.getTemplate.mockResolvedValue({ ...SLACK_TEMPLATE, id: props.templateId })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(
            flagOn ? [FEATURE_FLAGS.WORKFLOWS_MESSAGING_DESTINATIONS] : [],
            flagOn ? { [FEATURE_FLAGS.WORKFLOWS_MESSAGING_DESTINATIONS]: true } : {}
        )

        router.actions.push(urls.hogFunctionNew(props.templateId))
        const logic = hogFunctionSceneLogic(props)
        logic.mount()

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(expectedPath)
        logic.unmount()
    })
})
