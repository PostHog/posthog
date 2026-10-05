import { selectAnswer } from './answer-selection'
import { AiDecisionConfig } from './config'

const yesNo = (overrides: Partial<AiDecisionConfig> = {}): AiDecisionConfig => ({
    question: 'Is this a work email?',
    answer_type: 'yes_no',
    options: [],
    yes_means: '',
    no_means: '',
    yes_threshold: 50,
    unsure_enabled: false,
    min_pick_probability: 60,
    no_threshold: 20,
    ...overrides,
})

const pickOne = (overrides: Partial<AiDecisionConfig> = {}): AiDecisionConfig =>
    yesNo({
        question: 'Which track fits?',
        answer_type: 'pick_one',
        options: [
            { name: 'Developer', description: '' },
            { name: 'Marketer', description: '' },
            { name: 'Founder', description: '' },
        ],
        ...overrides,
    })

describe('selectAnswer', () => {
    it.each([
        ['yes at the threshold', yesNo(), 0.5, { answer: 'yes', branchIndex: 0, probability: 0.5 }],
        ['no just under the threshold', yesNo(), 0.4999, { answer: 'no', branchIndex: 1, probability: 0.4999 }],
        [
            'yes above a raised threshold',
            yesNo({ yes_threshold: 50 }),
            0.62,
            { answer: 'yes', branchIndex: 0, probability: 0.62 },
        ],
        [
            'a threshold that does not divide evenly',
            yesNo({ yes_threshold: 29 }),
            0.29,
            { answer: 'yes', branchIndex: 0, probability: 0.29 },
        ],
        [
            'no below the band when unsure is on',
            yesNo({ unsure_enabled: true, yes_threshold: 80, no_threshold: 20 }),
            0.2,
            { answer: 'no', branchIndex: 1, probability: 0.2 },
        ],
        [
            'unsure just above the no threshold',
            yesNo({ unsure_enabled: true, yes_threshold: 80, no_threshold: 20 }),
            0.2001,
            { answer: 'unsure', branchIndex: 2, probability: 0.2001 },
        ],
        [
            'unsure just under the yes threshold',
            yesNo({ unsure_enabled: true, yes_threshold: 80, no_threshold: 20 }),
            0.7999,
            { answer: 'unsure', branchIndex: 2, probability: 0.7999 },
        ],
        [
            'yes at the threshold when unsure is on',
            yesNo({ unsure_enabled: true, yes_threshold: 80, no_threshold: 20 }),
            0.8,
            { answer: 'yes', branchIndex: 0, probability: 0.8 },
        ],
    ])('yes or no: %s', (_name, config, pYes, expected) => {
        expect(selectAnswer(config, { yes: pYes, no: 1 - pYes })).toEqual(expected)
    })

    it.each([
        [
            'the top option',
            pickOne(),
            { Developer: 0.2, Marketer: 0.7, Founder: 0.1 },
            { answer: 'Marketer', branchIndex: 1, probability: 0.7 },
        ],
        [
            'the earlier option on a tie',
            pickOne(),
            { Developer: 0.1, Marketer: 0.45, Founder: 0.45 },
            { answer: 'Marketer', branchIndex: 1, probability: 0.45 },
        ],
        [
            'a low top option when unsure is off',
            pickOne(),
            { Developer: 0.34, Marketer: 0.33, Founder: 0.33 },
            { answer: 'Developer', branchIndex: 0, probability: 0.34 },
        ],
        [
            'unsure when the top option is under the minimum',
            pickOne({ unsure_enabled: true, min_pick_probability: 60 }),
            { Developer: 0.5999, Marketer: 0.3, Founder: 0.1001 },
            { answer: 'unsure', branchIndex: 3, probability: 0.5999 },
        ],
        [
            'the top option at the minimum',
            pickOne({ unsure_enabled: true, min_pick_probability: 60 }),
            { Developer: 0.1, Marketer: 0.3, Founder: 0.6 },
            { answer: 'Founder', branchIndex: 2, probability: 0.6 },
        ],
    ])('pick one: %s', (_name, config, probabilities, expected) => {
        expect(selectAnswer(config, probabilities)).toEqual(expected)
    })

    it.each([
        ['yes or no without a yes probability', yesNo(), { no: 0.4 }],
        ['pick one missing an option', pickOne(), { Developer: 0.5, Marketer: 0.5 }],
    ])('rejects %s', (_name, config, probabilities) => {
        expect(() => selectAnswer(config, probabilities)).toThrow()
    })
})
