import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

export type CyclotronJobInputsValidationResult = {
    valid: boolean
    errors: Record<string, string>
}

export class CyclotronJobInputsValidation {
    // Returns a list an object of errors for each input
    static validate(
        inputs: Record<string, CyclotronJobInputType>,
        inputsSchema: CyclotronJobInputSchemaType[]
    ): CyclotronJobInputsValidationResult {
        return {
            valid: false,
            errors: { foo: 'bar' },
        }
    }
}
