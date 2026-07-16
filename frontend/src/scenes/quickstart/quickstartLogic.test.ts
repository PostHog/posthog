import { QuickstartJourneyStep, QuickstartTaskGuide, orderJourneyAchievements } from './quickstartLogic'

const guide: QuickstartTaskGuide = {
    description: 'Test guidance',
    instructions: ['Test instruction'],
    action: 'open_product',
    actionLabel: 'Open product',
}

function journeyStep(key: string, kind: QuickstartJourneyStep['kind'], achieved: boolean): QuickstartJourneyStep {
    return { key, label: key, kind, achieved, guide }
}

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
