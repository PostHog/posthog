import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import {
    HEALTH_ALERT_DESTINATIONS,
    HEALTH_ALERT_SUB_TEMPLATE_IDS,
    HEALTH_ALERT_TRIGGERS,
} from 'scenes/health-alerts/healthAlertsWizardConfig'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

import { alertWizardLogic, applyKindFilter, decorateAlertName, testInvocationFailureMessage } from './alertWizardLogic'

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

        it('falls back to the raw kind when no label is registered', () => {
            expect(decorateAlertName(baseName, ['some_future_kind'])).toBe(
                'Email when a Health check fires (some_future_kind)'
            )
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
