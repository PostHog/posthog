const MAX_FRAME_COUNT = 4
const MAX_FRAME_NAME_LENGTH = 128
const FRAME_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/

export type GenUIInputValidation = {
    names: string[]
    error: string | null
}

export function validateGenUIInputs(inputs: string): GenUIInputValidation {
    const names = inputs
        .split(/[\s,]+/)
        .map((name) => name.trim())
        .filter(Boolean)
    const invalidName = names.find((name) => name.length > MAX_FRAME_NAME_LENGTH || !FRAME_NAME.test(name))
    if (invalidName) {
        return { names: [], error: `"${invalidName}" is not a valid dataframe name.` }
    }
    const duplicateName = names.find((name, index) => names.indexOf(name) !== index)
    if (duplicateName) {
        return { names: [], error: `Dataframe "${duplicateName}" is listed more than once.` }
    }
    if (names.length > MAX_FRAME_COUNT) {
        return { names: [], error: `Choose no more than ${MAX_FRAME_COUNT} dataframes.` }
    }
    return { names, error: null }
}
