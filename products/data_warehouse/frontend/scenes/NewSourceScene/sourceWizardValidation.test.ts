import type { SourceFieldConfig } from '~/queries/schema/schema-general'

import { normalizeMultiValue } from '../../shared/components/forms/IntegrationAccountSelector'
import { getErrorsForFields } from './sourceWizardLogic'

const REPOSITORIES_FIELD: SourceFieldConfig = {
    type: 'oauth-account-select',
    name: 'repositories',
    label: 'Repositories',
    integrationField: 'github_integration_id',
    integrationKind: 'github',
    required: true,
    multiple: true,
}

describe('source wizard multi-value fields', () => {
    describe('getErrorsForFields', () => {
        // An empty array is truthy, so without the explicit length check "Next" would proceed
        // with zero repositories selected.
        it.each([
            [[], 'Please enter at least one of your repositories'],
            [undefined, 'Please enter a repositories'],
            [['posthog/posthog'], undefined],
        ])('required multi field with value %p yields error %p', (value, expectedError) => {
            const errors = getErrorsForFields([REPOSITORIES_FIELD], {
                prefix: '',
                payload: { repositories: value },
            })
            expect(errors.payload.repositories).toEqual(expectedError)
        })

        it('does not flag optional multi fields', () => {
            const errors = getErrorsForFields([{ ...REPOSITORIES_FIELD, required: false }], {
                prefix: '',
                payload: { repositories: [] },
            })
            expect(errors.payload.repositories).toBeUndefined()
        })
    })

    describe('normalizeMultiValue', () => {
        it.each([
            [undefined, undefined, []],
            ['', undefined, []],
            ['a/b', undefined, ['a/b']],
            [[' a/b ', 'a/b', '', 'c/d'], undefined, ['a/b', 'c/d']],
            // Legacy single-repo sources only store `repository`; it must seed the picker.
            [[], 'legacy/repo', ['legacy/repo']],
            [['a/b'], 'legacy/repo', ['a/b']],
        ])('value %p with legacy %p normalizes to %p', (value, legacy, expected) => {
            expect(normalizeMultiValue(value, legacy)).toEqual(expected)
        })
    })
})
