import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

export type CyclotronJobInputsValidationResult = {
    valid: boolean
    errors: Record<string, string>
}

export class CyclotronJobInputsValidation {
    // Returns a list an object of errors for each input
    static validate(
        // oxlint-disable-next-line no-unused-vars
        _inputs: Record<string, CyclotronJobInputType>,
        // oxlint-disable-next-line no-unused-vars
        _inputsSchema: CyclotronJobInputSchemaType[]
    ): CyclotronJobInputsValidationResult {
        return {
            valid: false,
            errors: { foo: 'bar', url: 'bar' },
        }
    }
}
