import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

import { WizardDestination, WizardStep, alertWizardLogic, applyKindFilter, decorateAlertName } from './alertWizardLogic'

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

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

describe('alertWizardLogic', () => {
    let logic: ReturnType<typeof alertWizardLogic.build>

    const SLACK: WizardDestination = {
        key: 'slack',
        name: 'Slack',
        description: 'Send a message to a channel',
        icon: '/static/services/slack.png',
        templateId: 'template-slack',
    }
    const GITHUB: WizardDestination = {
        key: 'github',
        name: 'GitHub',
        description: 'Create an issue in a repository',
        icon: '/static/services/github.png',
        templateId: 'template-github',
    }

    const templateResponse = (id: string): Record<string, any> => ({
        id,
        type: 'internal_destination',
        name: id,
        status: 'stable',
        free: true,
        code: 'return event',
        code_language: 'hog',
        inputs_schema: [{ key: `${id}-field`, type: 'string', label: `${id} field`, required: true }],
    })

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_functions/': { results: [], next: null },
                '/api/projects/:team_id/hog_function_templates/:id': (req) => [
                    200,
                    templateResponse(req.params.id as string),
                ],
            },
        })
        initKeaTests()
        logic = alertWizardLogic({
            logicKey: 'test',
            subTemplateIds: ['error-tracking-issue-created'],
            triggers: [
                {
                    key: 'error-tracking-issue-created',
                    name: 'Issue created',
                    description: 'A new issue is detected',
                },
                {
                    key: 'error-tracking-issue-reopened',
                    name: 'Issue reopened',
                    description: 'A resolved issue comes back',
                },
            ],
            destinations: [SLACK, GITHUB],
            disableUrlSync: true,
        })
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('clears the trigger when the destination changes', async () => {
        await expectLogic(logic, () => {
            logic.actions.setDestinationKey('slack')
            logic.actions.setTriggerKey('error-tracking-issue-reopened')
        }).toMatchValues({ selectedTriggerKey: 'error-tracking-issue-reopened' })

        await expectLogic(logic, () => logic.actions.setDestinationKey('github')).toMatchValues({
            selectedTriggerKey: null,
            currentStep: WizardStep.Trigger,
        })
    })

    it('does not expose the previous destination template after the destination changes', async () => {
        await expectLogic(logic, () => {
            logic.actions.setDestinationKey('slack')
            logic.actions.setTriggerKey('error-tracking-issue-created')
        })
            .delay(0)
            .toMatchValues({
                activeTemplate: expect.objectContaining({ id: 'template-slack' }),
                requiredInputsSchema: [expect.objectContaining({ key: 'template-slack-field' })],
            })

        await expectLogic(logic, () => logic.actions.setDestinationKey('github')).toMatchValues({
            activeTemplate: null,
            requiredInputsSchema: [],
        })
    })

    it('reports a missing trigger instead of submitting nothing', async () => {
        logic.actions.setDestinationKey('slack')
        logic.actions.setTriggerKey('error-tracking-issue-created')
        await expectLogic(logic).delay(0)

        // Reaching configure with no trigger is what a stale destination change used to leave behind.
        logic.actions.restoreWizardState({
            step: WizardStep.Configure,
            destinationKey: 'slack',
            triggerKey: null,
        })

        await expectLogic(logic, () => logic.actions.submitConfiguration())
            .delay(0)
            .toMatchValues({ currentStep: WizardStep.Trigger, submitting: false })
        expect(lemonToast.error).toHaveBeenCalledWith('Choose what should trigger this alert first.')
    })

    it('marks the template as failed to load so the configure step can offer a retry', async () => {
        useMocks({ get: { '/api/projects/:team_id/hog_function_templates/:id': () => [500, {}] } })

        logic.actions.setDestinationKey('slack')
        await expectLogic(logic, () => logic.actions.setTriggerKey('error-tracking-issue-created'))
            .delay(0)
            .toMatchValues({ templateLoadFailed: true, activeTemplate: null })

        useMocks({
            get: {
                '/api/projects/:team_id/hog_function_templates/:id': (req) => [
                    200,
                    templateResponse(req.params.id as string),
                ],
            },
        })
        await expectLogic(logic, () => logic.actions.retryLoadTemplate())
            .delay(0)
            .toMatchValues({
                templateLoadFailed: false,
                activeTemplate: expect.objectContaining({ id: 'template-slack' }),
            })
    })
})
