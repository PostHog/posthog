import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { CyclotronJobFiltersType, HogFunctionSubTemplateIdType, PropertyFilterType, PropertyOperator } from '~/types'

import {
    ERROR_TRACKING_DESTINATIONS,
    ERROR_TRACKING_SUB_TEMPLATE_IDS,
    ERROR_TRACKING_TRIGGERS,
} from 'products/error_tracking/frontend/scenes/ErrorTrackingConfigurationScene/alerting/alertWizardConfig'

import { alertWizardLogic, applyKindFilter, decorateAlertName } from './alertWizardLogic'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    hogFunctions: {
        list: jest.fn().mockResolvedValue({ results: [] }),
    },
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

describe('alertWizardLogic availableDestinations', () => {
    let logic: ReturnType<typeof alertWizardLogic.build>

    function mountWithPresetTrigger(presetTriggerKey?: HogFunctionSubTemplateIdType): void {
        logic = alertWizardLogic({
            logicKey: 'test',
            subTemplateIds: ERROR_TRACKING_SUB_TEMPLATE_IDS,
            triggers: ERROR_TRACKING_TRIGGERS,
            destinations: ERROR_TRACKING_DESTINATIONS,
            disableUrlSync: true,
            presetTriggerKey,
        })
        logic.mount()
    }

    beforeEach(() => {
        jest.clearAllMocks()
        ;(api.hogFunctions.list as jest.Mock).mockResolvedValue({ results: [] })
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    // Guards the recommendation-modal flow: with a preset trigger, only destinations
    // that have a sub-template for that trigger may be offered — otherwise picking one
    // dead-ends at "Template not found for this combination".
    it.each([
        ['error-tracking-issue-created', ['slack', 'discord', 'github', 'gitlab', 'microsoft-teams', 'linear']],
        ['error-tracking-issue-reopened', ['slack', 'discord', 'microsoft-teams']],
        ['error-tracking-issue-spiking', ['slack', 'discord', 'microsoft-teams']],
    ])('offers only destinations with a sub-template for preset trigger %s', (triggerKey, expectedKeys) => {
        mountWithPresetTrigger(triggerKey as HogFunctionSubTemplateIdType)
        expect(logic.values.availableDestinations.map((d) => d.key).sort()).toEqual([...expectedKeys].sort())
    })

    it('offers every destination when no trigger is selected yet', () => {
        mountWithPresetTrigger(undefined)
        expect(logic.values.availableDestinations).toHaveLength(ERROR_TRACKING_DESTINATIONS.length)
    })
})
