import type { SourceFieldConfig } from '~/queries/schema/schema-general'

import { findOauthBranch, normalizeMultiValue } from '../../shared/components/forms/IntegrationAccountSelector'
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

// Mirrors GitHub's auth select: the OAuth field is `required: false` so stored PAT configs keep
// parsing, which used to let an empty OAuth submit through to a guaranteed credentials error.
const AUTH_METHOD_FIELD: SourceFieldConfig = {
    type: 'select',
    name: 'auth_method',
    label: 'Authentication type',
    required: true,
    defaultValue: 'oauth',
    options: [
        {
            label: 'OAuth (GitHub App)',
            value: 'oauth',
            fields: [
                {
                    type: 'oauth',
                    name: 'github_integration_id',
                    label: 'GitHub account',
                    required: false,
                    kind: 'github',
                },
            ],
        },
        {
            label: 'Personal access token',
            value: 'pat',
            fields: [
                {
                    type: 'text',
                    name: 'personal_access_token',
                    label: 'Personal access token',
                    required: false,
                    placeholder: '',
                    secret: true,
                },
            ],
        },
    ],
}

describe('source wizard multi-value fields', () => {
    describe('getErrorsForFields', () => {
        // An empty array is truthy, so without the explicit length check "Next" would proceed
        // with zero repositories selected.
        it.each([
            [[], 'Please enter at least one of your repositories'],
            [undefined, 'Repositories is required'],
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

        it.each([
            [{ selection: 'oauth' }, 'Select or connect a GitHub account'],
            [{ selection: 'oauth', github_integration_id: 42 }, undefined],
            [{ selection: 'pat', personal_access_token: 'token' }, undefined],
        ])('oauth field on the selected branch with payload %p yields error %p', (authMethod, expectedError) => {
            const errors = getErrorsForFields([AUTH_METHOD_FIELD], {
                prefix: '',
                payload: { auth_method: authMethod },
            })
            expect(errors.payload.auth_method?.github_integration_id).toEqual(expectedError)
        })
    })

    describe('findOauthBranch', () => {
        // A wrong branch lookup either disables the repositories picker for PAT users or skips
        // the connect prompt for OAuth users; both are user-blocking.
        it.each([
            ['github_integration_id', { selectField: 'auth_method', optionValue: 'oauth', defaultValue: 'oauth' }],
            ['personal_access_token', undefined],
            ['not_a_field', undefined],
        ])('locates %p as %p', (integrationField, expected) => {
            expect(findOauthBranch([AUTH_METHOD_FIELD, REPOSITORIES_FIELD], integrationField)).toEqual(expected)
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
