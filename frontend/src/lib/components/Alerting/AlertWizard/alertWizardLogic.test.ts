import {
    CyclotronJobFiltersType,
    CyclotronJobInputSchemaType,
    HogFunctionTemplateType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { applyKindFilter, decorateAlertName, firstErrorMessage, requiredInputsToConfigure } from './alertWizardLogic'

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

describe('requiredInputsToConfigure', () => {
    const input = (
        key: string,
        type: CyclotronJobInputSchemaType['type'],
        required: boolean
    ): CyclotronJobInputSchemaType => ({ key, type, required, label: key })
    const templateWith = (...inputs_schema: CyclotronJobInputSchemaType[]): HogFunctionTemplateType =>
        ({ inputs_schema }) as HogFunctionTemplateType

    // A required input the configure step can't render leaves the user with a form they can never
    // complete: the field is invisible, so it's never submitted, and the save fails server-side.
    it.each([
        ['string', true],
        ['choice', true],
        ['integration', true],
        ['integration_field', true],
        ['json', false],
    ] as [CyclotronJobInputSchemaType['type'], boolean][])('renders a required %s input: %s', (type, rendered) => {
        const result = requiredInputsToConfigure(templateWith(input('field', type, true)), null)
        expect(result.map((s) => s.key)).toEqual(rendered ? ['field'] : [])
    })

    it('skips optional inputs and inputs the sub-template already fills in', () => {
        const template = templateWith(
            input('webhookUrl', 'string', true),
            input('content', 'string', true),
            input('note', 'string', false)
        )
        const result = requiredInputsToConfigure(template, { inputs: { content: { value: 'hi' } } } as any)
        expect(result.map((s) => s.key)).toEqual(['webhookUrl'])
    })
})

describe('firstErrorMessage', () => {
    it.each([
        [
            'a nested field error from the test invocation endpoint',
            { configuration: { inputs: { allowedMentions: ['This field is required.'] } } },
            'allowedMentions: This field is required.',
        ],
        [
            'a top-level non-field error',
            { configuration: { non_field_errors: ['Invalid filters'] } },
            'Invalid filters',
        ],
        ['no error at all', {}, null],
    ])('describes %s', (_, data, expected) => {
        expect(firstErrorMessage(data)).toBe(expected)
    })
})
