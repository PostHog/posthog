import { AiDecisionConfig } from './config'

export type SelectedAnswer = { answer: string; branchIndex: number; probability: number }

const YES = 0
const NO = 1
const YES_NO_UNSURE = 2

function probabilityOf(probabilities: Record<string, number>, answer: string): number {
    const probability = Object.hasOwn(probabilities, answer) ? probabilities[answer] : undefined
    if (typeof probability !== 'number' || !Number.isFinite(probability) || probability < 0 || probability > 1) {
        throw new Error(`The model returned no valid probability for "${answer}".`)
    }
    return probability
}

// Thresholds are whole percents. Dividing keeps 29% equal to 0.29, where 0.29 * 100 would fall just under 29.
function atLeast(probability: number, percent: number): boolean {
    return probability >= percent / 100
}

function atMost(probability: number, percent: number): boolean {
    return probability <= percent / 100
}

function yesNoBranch(config: AiDecisionConfig, pYes: number): number {
    if (atLeast(pYes, config.yes_threshold)) {
        return YES
    }
    if (config.unsure_enabled && !atMost(pYes, config.no_threshold)) {
        return YES_NO_UNSURE
    }
    return NO
}

function selectYesNo(config: AiDecisionConfig, probabilities: Record<string, number>): SelectedAnswer {
    const pYes = probabilityOf(probabilities, 'yes')
    const branchIndex = yesNoBranch(config, pYes)
    return { answer: ['yes', 'no', 'unsure'][branchIndex], branchIndex, probability: pYes }
}

function topOptionIndex(values: number[]): number {
    // A strict comparison keeps the earlier option on a tie.
    return values.reduce((top, value, index) => (value > values[top] ? index : top), 0)
}

function selectPickOne(config: AiDecisionConfig, probabilities: Record<string, number>): SelectedAnswer {
    const values = config.options.map((option) => probabilityOf(probabilities, option.name))
    const top = topOptionIndex(values)
    const probability = values[top]
    if (config.unsure_enabled && !atLeast(probability, config.min_pick_probability)) {
        return { answer: 'unsure', branchIndex: config.options.length, probability }
    }
    return { answer: config.options[top].name, branchIndex: top, probability }
}

export function selectAnswer(config: AiDecisionConfig, probabilities: Record<string, number>): SelectedAnswer {
    return config.answer_type === 'yes_no' ? selectYesNo(config, probabilities) : selectPickOne(config, probabilities)
}
