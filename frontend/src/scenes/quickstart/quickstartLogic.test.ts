import { ProductKey } from '~/queries/schema/schema-general'

import { QUICKSTART_PRODUCT_LAYOUT, getQuickstartProductSections } from './productLayout'
import {
    QuickstartJourneyStep,
    QuickstartTaskGuide,
    orderJourneyAchievements,
    shouldRedirectFromQuickstart,
} from './quickstartLogic'

const guide: QuickstartTaskGuide = {
    description: 'Test guidance',
    instructions: ['Test instruction'],
    action: 'open_product',
    actionLabel: 'Open product',
}

function journeyStep(key: string, kind: QuickstartJourneyStep['kind'], achieved: boolean): QuickstartJourneyStep {
    return { key, label: key, kind, achieved, guide }
}

describe('quickstartLogic', () => {
    describe('product sections', () => {
        const products = [
            { key: ProductKey.PRODUCT_ANALYTICS },
            { key: ProductKey.WEB_ANALYTICS },
            { key: ProductKey.SESSION_REPLAY },
            { key: ProductKey.ERROR_TRACKING },
            { key: ProductKey.FEATURE_FLAGS },
        ]

        it('uses the code-configured featured products by default', () => {
            const sections = getQuickstartProductSections(products, {})

            expect(sections.featuredProducts.map(({ key }) => key)).toEqual(
                QUICKSTART_PRODUCT_LAYOUT.featured.productKeys
            )
            expect(sections.additionalProducts.map(({ key }) => key)).toEqual([
                ProductKey.WEB_ANALYTICS,
                ProductKey.ERROR_TRACKING,
            ])
        })

        it('applies explicit promotion and demotion overrides without changing product order', () => {
            const sections = getQuickstartProductSections(products, {
                [ProductKey.SESSION_REPLAY]: false,
                [ProductKey.ERROR_TRACKING]: true,
            })

            expect(sections.featuredProducts.map(({ key }) => key)).toEqual([
                ProductKey.PRODUCT_ANALYTICS,
                ProductKey.ERROR_TRACKING,
                ProductKey.FEATURE_FLAGS,
            ])
            expect(sections.additionalProducts.map(({ key }) => key)).toEqual([
                ProductKey.WEB_ANALYTICS,
                ProductKey.SESSION_REPLAY,
            ])
        })
    })

    describe('orderJourneyAchievements', () => {
        test.each([
            {
                name: 'keeps quality pending until the tool is live',
                live: false,
                journey: [
                    journeyStep('install', 'activation', true),
                    journeyStep('signal', 'activation', false),
                    journeyStep('quality-one', 'quality', true),
                ],
                expected: [true, false, false],
            },
            {
                name: 'treats activation as complete once live and stops quality at the first gap',
                live: true,
                journey: [
                    journeyStep('install', 'activation', false),
                    journeyStep('signal', 'activation', true),
                    journeyStep('quality-one', 'quality', true),
                    journeyStep('quality-two', 'quality', false),
                    journeyStep('quality-three', 'quality', true),
                ],
                expected: [true, true, true, false, false],
            },
            {
                name: 'keeps a fully ordered live journey complete',
                live: true,
                journey: [
                    journeyStep('install', 'activation', true),
                    journeyStep('signal', 'activation', true),
                    journeyStep('quality-one', 'quality', true),
                    journeyStep('quality-two', 'quality', true),
                ],
                expected: [true, true, true, true],
            },
        ])('$name', ({ live, journey, expected }) => {
            expect(orderJourneyAchievements(journey, live).map((step) => step.achieved)).toEqual(expected)
        })
    })

    describe('shouldRedirectFromQuickstart', () => {
        test.each([
            { receivedFeatureFlags: false, variant: undefined, expected: false },
            { receivedFeatureFlags: true, variant: 'test', expected: false },
            { receivedFeatureFlags: true, variant: 'control', expected: true },
            { receivedFeatureFlags: true, variant: undefined, expected: true },
        ])(
            'returns $expected for received=$receivedFeatureFlags and variant=$variant',
            ({ receivedFeatureFlags, variant, expected }) => {
                expect(shouldRedirectFromQuickstart(receivedFeatureFlags, variant)).toBe(expected)
            }
        )
    })
})
