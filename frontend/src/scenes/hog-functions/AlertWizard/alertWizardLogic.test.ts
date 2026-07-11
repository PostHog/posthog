import { HOG_FUNCTION_SUB_TEMPLATES } from 'scenes/hog-functions/sub-templates/sub-templates'

import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

import {
    ERROR_TRACKING_DESTINATIONS,
    ERROR_TRACKING_TRIGGERS,
} from 'products/error_tracking/frontend/scenes/ErrorTrackingConfigurationScene/alerting/alertWizardConfig'

import { applyKindFilter, decorateAlertName } from './alertWizardLogic'

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

// The recommendation "Create alert" entry point presets a trigger and skips the Trigger
// step, so every destination offered for error tracking must have a sub-template for every
// trigger — otherwise the combo dead-ends at submit with "Template not found for this
// combination". This guards against adding a trigger/destination without its sub-template.
describe('error-tracking trigger/destination sub-template coverage', () => {
    const combos = ERROR_TRACKING_TRIGGERS.flatMap((trigger) =>
        ERROR_TRACKING_DESTINATIONS.map((destination) => ({
            triggerKey: trigger.key,
            destinationKey: destination.key,
            templateId: destination.templateId,
        }))
    )

    it.each(combos)(
        'has a sub-template for trigger $triggerKey → destination $destinationKey',
        ({ triggerKey, templateId }) => {
            const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[triggerKey]
            expect(subTemplates.some((t) => t.template_id === templateId)).toBe(true)
        }
    )
})
