import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

import {
    AlertWizardLogicProps,
    WizardStep,
    alertWizardLogic,
    applyKindFilter,
    decorateAlertName,
} from './alertWizardLogic'

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

describe('redirect snapshot restore', () => {
    // Regression coverage for the "Connect to Slack" full-page redirect wiping out the wizard:
    // persistForUnload stashes position + input values right before the OAuth navigation, and a
    // fresh mount of the same logic (as happens after the browser reloads) must pick them back up.
    const buildProps = (logicKey: string): AlertWizardLogicProps => ({
        logicKey,
        subTemplateIds: ['error-tracking-issue-created'],
        triggers: [{ key: 'error-tracking-issue-created', name: 'Issue created', description: '' }],
        destinations: [{ key: 'slack', name: 'Slack', description: '', icon: '', templateId: 'template-slack' }],
        disableUrlSync: true,
        presetTriggerKey: 'error-tracking-issue-created',
    })

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
    })

    it('restores step, destination and input values after a fresh mount within the TTL', async () => {
        const logicKey = 'redirect-restore-fresh'
        const first = alertWizardLogic.build(buildProps(logicKey))
        first.mount()
        first.actions.setDestinationKey('slack')
        first.actions.setInputValue('message', { value: 'hello' })
        first.actions.persistForUnload()
        first.unmount()

        const second = alertWizardLogic.build(buildProps(logicKey))
        second.mount()
        await expectLogic(second).toDispatchActions(['restoreWizardState', 'restoreInputValues'])

        expect(second.values.currentStep).toBe(WizardStep.Configure)
        expect(second.values.selectedDestinationKey).toBe('slack')
        expect(second.values.inputValues).toEqual({ message: { value: 'hello' } })
        expect(second.values.redirectSnapshot).toBeNull()

        second.unmount()
    })

    it('does not restore a snapshot older than the TTL', async () => {
        const logicKey = 'redirect-restore-stale'
        const first = alertWizardLogic.build(buildProps(logicKey))
        first.mount()
        first.actions.setDestinationKey('slack')
        jest.spyOn(Date, 'now').mockReturnValue(Date.now() - 1000 * 60 * 10)
        first.actions.persistForUnload()
        jest.spyOn(Date, 'now').mockRestore()
        first.unmount()

        const second = alertWizardLogic.build(buildProps(logicKey))
        second.mount()
        await expectLogic(second).toFinishAllListeners()

        expect(second.values.currentStep).toBe(WizardStep.Destination)
        expect(second.values.selectedDestinationKey).toBeNull()
        expect(second.values.redirectSnapshot).toBeNull()

        second.unmount()
    })
})
