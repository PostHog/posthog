import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import {
    HEALTH_ALERT_DESTINATIONS,
    HEALTH_ALERT_SUB_TEMPLATE_IDS,
    HEALTH_ALERT_TRIGGERS,
} from 'scenes/health-alerts/healthAlertsWizardConfig'
import { HOG_FUNCTION_SUB_TEMPLATES } from 'scenes/hog-functions/sub-templates/sub-templates'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    CyclotronJobFilterPropertyFilter,
    CyclotronJobFiltersType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import {
    AlertWizardLogicProps,
    alertWizardLogic,
    applyKindFilter,
    applyPresetFilters,
    buildAlertHogFunctionConfiguration,
    decorateAlertName,
    testInvocationFailureMessage,
} from './alertWizardLogic'

describe('alertWizardLogic', () => {
    describe('applyKindFilter', () => {
        const baseFilters: CyclotronJobFiltersType = {
            events: [{ id: '$health_check_issue_firing', type: 'events' }],
        }

        it.each([
            ['null', null],
            ['an empty array', [] as string[]],
        ])('returns filters unchanged when selectedKinds is %s', (_, kinds) => {
            expect(applyKindFilter(baseFilters, kinds)).toBe(baseFilters)
        })

        it('returns undefined when base filters are undefined', () => {
            expect(applyKindFilter(undefined, ['sdk_outdated'])).toBeUndefined()
        })

        it('adds a top-level kind IN (...) property filter', () => {
            const result = applyKindFilter(baseFilters, ['sdk_outdated', 'ingestion_warning'])
            expect(result?.events?.[0]).toEqual({
                id: '$health_check_issue_firing',
                type: 'events',
            })
            expect(result?.properties).toEqual([
                {
                    key: 'kind',
                    value: ['sdk_outdated', 'ingestion_warning'],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ])
        })

        it('replaces any existing top-level properties', () => {
            const withProps: CyclotronJobFiltersType = {
                ...baseFilters,
                properties: [
                    {
                        key: 'some_other',
                        value: 'x',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
            }
            const result = applyKindFilter(withProps, ['sdk_outdated'])
            expect(result?.properties).toHaveLength(1)
            expect(result?.properties?.[0].key).toBe('kind')
        })

        it('leaves events untouched', () => {
            const twoEvents: CyclotronJobFiltersType = {
                events: [
                    { id: '$health_check_issue_firing', type: 'events' },
                    { id: '$other_event', type: 'events' },
                ],
            }
            const result = applyKindFilter(twoEvents, ['sdk_outdated'])
            expect(result?.events).toEqual(twoEvents.events)
        })
    })

    describe('applyPresetFilters', () => {
        const baseFilters: CyclotronJobFiltersType = {
            events: [{ id: '$data_warehouse_sync_failed', type: 'events' }],
        }
        const sourceFilter: CyclotronJobFilterPropertyFilter = {
            key: 'source_id',
            value: ['source-1'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        }

        it.each([
            ['undefined', undefined],
            ['an empty array', [] as CyclotronJobFilterPropertyFilter[]],
        ])('matches applyKindFilter when presetPropertyFilters is %s', (_, preset) => {
            expect(applyPresetFilters(baseFilters, ['job_failed'], preset)).toEqual(
                applyKindFilter(baseFilters, ['job_failed'])
            )
            expect(applyPresetFilters(baseFilters, null, preset)).toBe(baseFilters)
        })

        it.each([
            ['no kinds', null, ['source_id']],
            ['kinds', ['job_failed'], ['kind', 'source_id']],
        ])('merges the preset filters beside %s', (_, kinds, expectedKeys) => {
            const result = applyPresetFilters(baseFilters, kinds, [sourceFilter])
            expect(result?.properties?.map((p) => ('key' in p ? p.key : null))).toEqual(expectedKeys)
            expect(result?.events).toEqual(baseFilters.events)
        })

        it('returns undefined when base filters are undefined', () => {
            expect(applyPresetFilters(undefined, null, [sourceFilter])).toBeUndefined()
        })
    })

    describe('buildAlertHogFunctionConfiguration', () => {
        const base = { templateId: 'template-slack', name: 'n', description: 'd', filters: null, inputs: {} }

        it.each([
            ['omitted', undefined, null],
            ['null', null, null],
            [
                'set',
                { hash: '{event.properties.schema_id}', ttl: 3600, threshold: null },
                { hash: '{event.properties.schema_id}', ttl: 3600, threshold: null },
            ],
        ])('passes masking through when it is %s', (_, masking, expected) => {
            expect(buildAlertHogFunctionConfiguration({ ...base, masking }).masking).toEqual(expected)
        })
    })

    describe('decorateAlertName', () => {
        const baseName = 'Email when a Health check fires'

        it.each([
            ['null', null],
            ['undefined', undefined],
            ['an empty array', [] as string[]],
        ])('returns the base name unchanged when selectedKinds is %s', (_, kinds) => {
            expect(decorateAlertName(baseName, kinds)).toBe(baseName)
        })

        it('appends a single kind label in parens', () => {
            expect(decorateAlertName(baseName, ['sdk_outdated'])).toBe('Email when a Health check fires (SDK outdated)')
        })

        it('joins multiple kind labels with commas', () => {
            expect(decorateAlertName(baseName, ['external_data_failure', 'materialized_view_failure'])).toBe(
                'Email when a Health check fires (External data failures, Materialized view failure)'
            )
        })

        it.each([
            ['without kinds', null, 'Email when a Health check fires for Stripe'],
            ['after the kinds', ['sdk_outdated'], 'Email when a Health check fires (SDK outdated) for Stripe'],
        ])('appends the name suffix %s', (_, kinds, expected) => {
            expect(decorateAlertName(baseName, kinds, 'for Stripe')).toBe(expected)
        })

        it('falls back to the raw kind when no label is registered', () => {
            expect(decorateAlertName(baseName, ['some_future_kind'])).toBe(
                'Email when a Health check fires (some_future_kind)'
            )
        })
    })

    describe('creating an alert', () => {
        const template = { id: 'template-slack', name: 'Slack', code: '', inputs_schema: [] }
        const sourceFilter: CyclotronJobFilterPropertyFilter = {
            key: 'source_id',
            value: ['source-1'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        }
        const healthSlackName = HOG_FUNCTION_SUB_TEMPLATES['health-check-firing'].find(
            (t) => t.template_id === 'template-slack'
        )?.name
        const dwhTriggers = [
            {
                key: 'data-warehouse-sync-completed',
                name: 'Sync completed',
                description: 'A table finished syncing',
            },
        ] as const

        async function createAlert(
            logicProps: Partial<AlertWizardLogicProps>,
            triggerKey: 'health-check-firing' | 'data-warehouse-sync-completed'
        ): Promise<{ payload: Record<string, any>; captureSpy: jest.SpyInstance }> {
            const createSpy = jest.spyOn(api.hogFunctions, 'create').mockResolvedValue({} as any)
            const captureSpy = jest.spyOn(posthog, 'capture').mockReturnValue(undefined)
            jest.spyOn(lemonToast, 'success').mockReturnValue('toast-id')

            const logic = alertWizardLogic({
                logicKey: 'create-test',
                subTemplateIds: HEALTH_ALERT_SUB_TEMPLATE_IDS,
                triggers: HEALTH_ALERT_TRIGGERS,
                destinations: HEALTH_ALERT_DESTINATIONS,
                ...logicProps,
            })
            logic.mount()
            logic.actions.setDestinationKey('slack')
            logic.actions.setTriggerKey(triggerKey)
            await expectLogic(logic, () => logic.actions.loadTemplate('template-slack')).toDispatchActions([
                'loadTemplateSuccess',
            ])
            await expectLogic(logic, () => logic.actions.submitConfiguration()).toDispatchActions([
                'createAlertSuccess',
            ])
            return { payload: createSpy.mock.calls[0][0] as Record<string, any>, captureSpy }
        }

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/environments/:team_id/hog_functions/': { count: 0, results: [] },
                    '/api/projects/:team_id/hog_functions/': { count: 0, results: [] },
                    '/api/environments/:team_id/hog_function_templates/template-slack/': template,
                    '/api/projects/:team_id/hog_function_templates/template-slack/': template,
                },
            })
            initKeaTests()
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('keeps the payload and event name unchanged when no new props are set', async () => {
            const { payload, captureSpy } = await createAlert({ contextId: 'health-alerts' }, 'health-check-firing')

            expect(payload.masking).toBeNull()
            expect(payload.filters.properties).toBeUndefined()
            expect(payload.name).toBe(healthSlackName)
            expect(captureSpy).toHaveBeenCalledWith('error_tracking_alert_created', expect.any(Object))
        })

        it('applies the preset filters, name suffix and event name', async () => {
            const { payload, captureSpy } = await createAlert(
                {
                    presetTriggerKinds: ['sdk_outdated'],
                    presetPropertyFilters: [sourceFilter],
                    nameSuffix: 'for Stripe',
                    createdEventName: 'custom_alert_created',
                },
                'health-check-firing'
            )

            expect(
                payload.filters.properties.map((p: CyclotronJobFilterPropertyFilter) => 'key' in p && p.key)
            ).toEqual(['kind', 'source_id'])
            expect(payload.name).toBe(`${healthSlackName} (SDK outdated) for Stripe`)
            expect(captureSpy).toHaveBeenCalledWith('custom_alert_created', expect.any(Object))
            expect(captureSpy).not.toHaveBeenCalledWith('error_tracking_alert_created', expect.any(Object))
        })

        it('passes the sub-template masking through', async () => {
            const { payload } = await createAlert(
                {
                    subTemplateIds: ['data-warehouse-sync-completed'],
                    triggers: [...dwhTriggers],
                },
                'data-warehouse-sync-completed'
            )

            expect(payload.masking).toMatchObject({ ttl: 3600 })
            expect(payload.masking.hash).toContain('event.properties.schema_id')
        })
    })

    describe('test invocation results', () => {
        const errorLog = { level: 'error', message: 'invalid_blocks' }
        const infoLog = { level: 'info', message: 'done' }

        it.each([
            ['a delivered test', { status: 'success', logs: [infoLog] }, null],
            ['a rejected test', { status: 'error', logs: [errorLog, infoLog] }, 'Test failed: invalid_blocks'],
            [
                'a rejected test with no error log',
                { status: 'error', logs: [infoLog] },
                'Test failed. Check the destination settings and try again.',
            ],
            [
                'a test whose inputs failed to build',
                { status: 'skipped', logs: [errorLog] },
                'Test failed: invalid_blocks',
            ],
            [
                'a filtered-out test event',
                { status: 'skipped', logs: [infoLog] },
                "Test not sent. The test event didn't match this alert's filters.",
            ],
        ])('reads %s', (_, result, expected) => {
            expect(testInvocationFailureMessage(result)).toBe(expected)
        })

        it.each([
            [
                'an error toast for a rejected test',
                { status: 'error', logs: [errorLog] },
                'error',
                'Test failed: invalid_blocks',
            ],
            [
                'a success toast for a delivered test',
                { status: 'success', logs: [] },
                'success',
                'Test invocation sent',
            ],
        ] as const)('shows %s', async (_, result, toast, message) => {
            const template = { id: 'template-slack', name: 'Slack', code: '', inputs_schema: [] }
            useMocks({
                get: {
                    '/api/environments/:team_id/hog_functions/': { count: 0, results: [] },
                    '/api/projects/:team_id/hog_functions/': { count: 0, results: [] },
                    '/api/environments/:team_id/hog_function_templates/template-slack/': template,
                    '/api/projects/:team_id/hog_function_templates/template-slack/': template,
                },
                post: {
                    '/api/projects/:team_id/hog_functions/new/invocations/': result,
                    '/api/environments/:team_id/hog_functions/new/invocations/': result,
                },
            })
            initKeaTests()
            const toastSpy = jest.spyOn(lemonToast, toast).mockReturnValue('toast-id')

            const logic = alertWizardLogic({
                logicKey: 'test',
                subTemplateIds: HEALTH_ALERT_SUB_TEMPLATE_IDS,
                triggers: HEALTH_ALERT_TRIGGERS,
                destinations: HEALTH_ALERT_DESTINATIONS,
                contextId: 'health-alerts',
            })
            logic.mount()
            logic.actions.setDestinationKey('slack')
            logic.actions.setTriggerKey('health-check-firing')
            await expectLogic(logic, () => logic.actions.loadTemplate('template-slack')).toDispatchActions([
                'loadTemplateSuccess',
            ])
            await expectLogic(logic, () => logic.actions.testConfiguration()).toDispatchActions([
                'testConfigurationComplete',
            ])

            expect(toastSpy).toHaveBeenCalledWith(message)
            toastSpy.mockRestore()
        })
    })
})
