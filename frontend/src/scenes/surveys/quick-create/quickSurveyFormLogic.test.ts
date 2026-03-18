import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

import { SURVEY_CREATED_SOURCE } from '../constants'
import { FunnelContext, toSurveyEvent } from '../utils/opportunityDetection'
import { quickSurveyFormLogic } from './quickSurveyFormLogic'
import { QuickSurveyType } from './types'
import { buildLogicProps } from './utils'

const mockFlag = {
    id: 123,
    name: 'my-feature-flag',
    filters: { groups: [], multivariate: null, payloads: {} },
} as unknown as FeatureFlagType

const mockFunnel: FunnelContext = {
    insightName: 'Checkout Funnel',
    conversionRate: 0.3,
    steps: [
        {
            kind: 'EventsNode',
            name: 'add_to_cart',
            properties: [{ key: 'category', value: ['electronics'], operator: 'exact' }],
        },
        { kind: 'EventsNode', name: 'checkout_complete' },
    ] as FunnelContext['steps'],
}

describe('buildLogicProps', () => {
    it('builds correct props for feature flag context', () => {
        const result = buildLogicProps({
            type: QuickSurveyType.FEATURE_FLAG,
            flag: mockFlag,
        })

        expect(result.key).toBe('flag-123')
        expect(result.source).toBe(SURVEY_CREATED_SOURCE.FEATURE_FLAGS)
        expect(result.contextType).toBe(QuickSurveyType.FEATURE_FLAG)
        expect(result.defaults.linkedFlagId).toBe(123)
        expect(result.defaults.name).toContain('my-feature-flag - Quick feedback')
    })

    it('includes initial variant in feature flag context when provided', () => {
        const result = buildLogicProps({
            type: QuickSurveyType.FEATURE_FLAG,
            flag: mockFlag,
            initialVariantKey: 'test-variant',
        })

        expect(result.defaults.name).toContain('my-feature-flag (test-variant) - Quick feedback')
        expect(result.defaults.conditions?.linkedFlagVariant).toBe('test-variant')
    })

    it('builds correct props for funnel context', () => {
        const result = buildLogicProps({
            type: QuickSurveyType.FUNNEL,
            funnel: mockFunnel,
        })

        expect(result.key).toBe('funnel-Checkout Funnel')
        expect(result.source).toBe(SURVEY_CREATED_SOURCE.INSIGHT_CROSS_SELL)
        expect(result.contextType).toBe(QuickSurveyType.FUNNEL)
        expect(result.defaults.linkedFlagId).toBeUndefined()
        expect(result.defaults.name).toContain('Checkout Funnel - Quick feedback')
        expect(result.defaults.conditions?.events?.values).toEqual([
            { name: 'add_to_cart', propertyFilters: { category: { values: ['electronics'], operator: 'exact' } } },
        ])
        expect(result.defaults.appearance?.surveyPopupDelaySeconds).toBe(15)
    })
})

describe('toSurveyEvent', () => {
    it('converts EventsNode to survey event format', () => {
        const step = {
            kind: 'EventsNode',
            name: 'purchase',
            properties: [
                { key: 'amount', value: ['100', '200'], operator: 'exact' },
                { key: 'currency', value: ['USD'], operator: 'exact' },
            ],
        } as FunnelContext['steps'][0]

        const result = toSurveyEvent(step as any)

        expect(result).toEqual({
            name: 'purchase',
            propertyFilters: {
                amount: { values: ['100', '200'], operator: 'exact' },
                currency: { values: ['USD'], operator: 'exact' },
            },
        })
    })

    it('handles step with no properties', () => {
        const step = { kind: 'EventsNode', name: 'pageview' } as FunnelContext['steps'][0]

        const result = toSurveyEvent(step as any)

        expect(result).toEqual({
            name: 'pageview',
            propertyFilters: {},
        })
    })
})

describe('quickSurveyFormLogic validation', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('returns error when question is empty', async () => {
        const logic = quickSurveyFormLogic({
            key: 'test-empty',
            source: SURVEY_CREATED_SOURCE.FEATURE_FLAGS,
            contextType: QuickSurveyType.FEATURE_FLAG,
            defaults: { question: '' },
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            surveyFormValidationErrors: expect.objectContaining({
                question: 'Please enter a question',
            }),
        })
    })

    it('returns no error when question is provided', async () => {
        const logic = quickSurveyFormLogic({
            key: 'test-valid',
            source: SURVEY_CREATED_SOURCE.FEATURE_FLAGS,
            contextType: QuickSurveyType.FEATURE_FLAG,
            defaults: { question: 'What do you think?' },
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            surveyFormValidationErrors: expect.objectContaining({
                question: undefined,
            }),
        })
    })
})
