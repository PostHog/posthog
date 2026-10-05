export type AiDecisionOption = { name: string; description: string }

export type AiDecisionConfig = {
    question: string
    answer_type: 'yes_no' | 'pick_one'
    options: AiDecisionOption[]
    yes_means: string
    no_means: string
    yes_threshold: number
    unsure_enabled: boolean
    min_pick_probability: number
    no_threshold: number
}

const MIN_OPTIONS = 2
const MAX_OPTIONS = 16
const MAX_QUESTION_LENGTH = 2000
const MAX_TEXT_LENGTH = 500
const MAX_CONTEXT_FIELD_NAME_LENGTH = 100

export function isPlainObject(value: unknown): value is Record<string, unknown> {
    return (
        value !== null &&
        typeof value === 'object' &&
        (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)
    )
}

// Django counts code points, so an emoji is one character on both sides rather than two UTF-16 units here.
function characterCount(text: string): number {
    return [...text].length
}

function requiredText(value: unknown, label: string, maxLength: number): string {
    const trimmed = typeof value === 'string' ? value.trim() : ''
    if (!trimmed || characterCount(trimmed) > maxLength) {
        throw new Error(`Enter ${label} of 1 to ${maxLength.toLocaleString('en-US')} characters.`)
    }
    return trimmed
}

function optionalText(value: unknown, label: string): string {
    const text = value === undefined ? '' : value
    if (typeof text !== 'string' || characterCount(text.trim()) > MAX_TEXT_LENGTH) {
        throw new Error(`Keep ${label} to ${MAX_TEXT_LENGTH} characters or fewer.`)
    }
    return text.trim()
}

function percent(value: unknown, fallback: number, label: string, maximum: number): number {
    const number = value === undefined ? fallback : value
    if (typeof number !== 'number' || !Number.isInteger(number) || number < 1 || number > maximum) {
        throw new Error(`Set the ${label} to a whole number from 1 to ${maximum}.`)
    }
    return number
}

function parseAnswerType(value: unknown): AiDecisionConfig['answer_type'] {
    if (value !== 'yes_no' && value !== 'pick_one') {
        throw new Error('Set the answer type to yes_no or pick_one.')
    }
    return value
}

function parseOption(option: unknown): AiDecisionOption {
    if (!isPlainObject(option)) {
        throw new Error(`Enter each option as a name of 1 to ${MAX_TEXT_LENGTH} characters and a description.`)
    }
    return {
        name: requiredText(option.name, 'an option name', MAX_TEXT_LENGTH),
        description: optionalText(option.description, 'each option description'),
    }
}

function parseOptions(value: unknown): AiDecisionOption[] {
    const options = value === undefined ? [] : value
    if (!Array.isArray(options) || options.length > MAX_OPTIONS) {
        throw new Error(`Enter between ${MIN_OPTIONS} and ${MAX_OPTIONS} options.`)
    }
    return options.map(parseOption)
}

function parseUnsureEnabled(value: unknown): boolean {
    const enabled = value === undefined ? false : value
    if (typeof enabled !== 'boolean') {
        throw new Error('Set unsure_enabled to true or false.')
    }
    return enabled
}

function checkAnswers(config: AiDecisionConfig): void {
    if (config.answer_type === 'pick_one') {
        if (config.options.length < MIN_OPTIONS) {
            throw new Error(`Enter between ${MIN_OPTIONS} and ${MAX_OPTIONS} options.`)
        }
        if (new Set(config.options.map((option) => option.name)).size !== config.options.length) {
            throw new Error('Give each option a different name.')
        }
    } else if (config.unsure_enabled && config.no_threshold >= config.yes_threshold) {
        throw new Error('Set the no threshold below the yes threshold.')
    }
}

function checkContextFields(inputs: unknown): void {
    const contextInput = isPlainObject(inputs) ? inputs.context : undefined
    const context = isPlainObject(contextInput) ? contextInput.value : undefined
    if (!isPlainObject(context) || Object.keys(context).length === 0) {
        throw new Error('Add at least one field for the model to read.')
    }
    const badName = (name: string): boolean => !name.trim() || characterCount(name) > MAX_CONTEXT_FIELD_NAME_LENGTH
    if (Object.keys(context).some(badName)) {
        throw new Error(`Give each context field a name of 1 to ${MAX_CONTEXT_FIELD_NAME_LENGTH} characters.`)
    }
}

/** Rejects exactly what a strict workflow save rejects, so a test run fails where a save would. */
export function parseAiDecisionConfig(raw: unknown): AiDecisionConfig {
    if (!isPlainObject(raw)) {
        throw new Error('Add a question for the model to answer.')
    }
    const config: AiDecisionConfig = {
        question: requiredText(raw.question, 'a question', MAX_QUESTION_LENGTH),
        answer_type: parseAnswerType(raw.answer_type),
        options: parseOptions(raw.options),
        yes_means: optionalText(raw.yes_means, 'what a yes means'),
        no_means: optionalText(raw.no_means, 'what a no means'),
        yes_threshold: percent(raw.yes_threshold, 50, 'yes threshold', 99),
        unsure_enabled: parseUnsureEnabled(raw.unsure_enabled),
        min_pick_probability: percent(raw.min_pick_probability, 60, 'minimum pick probability', 99),
        no_threshold: percent(raw.no_threshold, 20, 'no threshold', 98),
    }
    checkAnswers(config)
    checkContextFields(raw.inputs)
    return config
}

export function answersOf(config: AiDecisionConfig): string[] {
    const answers = config.answer_type === 'yes_no' ? ['yes', 'no'] : config.options.map((option) => option.name)
    return config.unsure_enabled ? [...answers, 'unsure'] : answers
}
