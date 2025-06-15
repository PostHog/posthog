/* global module */

const env = {
    browser: true,
    es6: true,
    'cypress/globals': true,
}

const globals = {
    Atomics: 'readonly',
    SharedArrayBuffer: 'readonly',
}

module.exports = {
    ignorePatterns: [
        'node_modules',
        'plugin-server',
        'rust',
        'livestream',
        'common/hogvm/typescript',
        'common/plugin_transpiler',
        'common/hogvm/__tests__/**/__snapshots__/**',
        'cypress/cypress.e2e.config.ts',
    ],
    env,
    settings: {
        react: {
            version: 'detect',
        },
        'import/resolver': {
            node: {
                paths: [
                    './common/eslint_rules',
                    '../common/eslint_rules',
                    '../../common/eslint_rules',
                    '../../../common/eslint_rules',
                ], // Add the directory containing your custom rules
                extensions: ['.js', '.jsx', '.ts', '.tsx'], // Ensure ESLint resolves both JS and TS files
            },
        },
    },
    extends: [
        'plugin:eslint-comments/recommended',
        'plugin:storybook/recommended',
        'plugin:compat/recommended',
        'prettier',
    ],
    globals,
    parser: '@typescript-eslint/parser',
    parserOptions: {
        project: true,
        tsconfigRootDir: __dirname,
    },
    plugins: [
        'react',
        'react-hooks',
        'cypress',
        '@typescript-eslint',
        'compat',
        'posthog',
        'simple-import-sort',
        'react-google-translate',
    ],
    rules: {
        // Rules not handled by Oxlint - keep only what's necessary
        
        // Import sorting - simple-import-sort provides more features than Oxlint's sort-imports
        'simple-import-sort/imports': 'error',
        'simple-import-sort/exports': 'error',

        // Custom PostHog rules - these cannot be migrated to Oxlint
        'posthog/warn-elements': [
            'warn',
            {
                forbid: [
                    {
                        element: 'Button',
                        message: 'use <LemonButton> instead',
                    },
                    {
                        element: 'Input',
                        message: 'use <LemonInput> instead',
                    },
                    {
                        element: 'Modal',
                        message: 'use <LemonModal> or `<LemonDialog> instead',
                    },
                    {
                        element: 'Select',
                        message: 'use <LemonSelect> instead',
                    },
                    {
                        element: 'LemonButtonWithDropdown',
                        message: 'use <LemonMenu> with a <LemonButton> child instead',
                    },
                    {
                        element: 'Progress',
                        message: 'use <LemonProgress> instead',
                    },
                ],
            },
        ],
        'posthog/no-schema-index-import': 'error',
        'posthog/no-survey-string-constants': 'warn',
        
        // React Google Translate plugin - not available in Oxlint
        'react-google-translate/no-conditional-text-nodes-with-siblings': 'warn',
        'react-google-translate/no-return-text-nodes': 'warn',
    },
    overrides: [
        {
            files: ['*Type.ts', '*Type.tsx'], // Kea typegen output
            rules: {
                'simple-import-sort/imports': 'off',
                'simple-import-sort/exports': 'off',
            },
        },
        {
            files: ['frontend/src/scenes/notebooks/Nodes/*'], // Notebooks code weirdly relies on its order of sorting
            rules: {
                'simple-import-sort/imports': 'off',
                'simple-import-sort/exports': 'off',
            },
        },
        {
            files: './common/eslint_rules/*',
            rules: {
                'posthog/no-survey-string-constants': 'off',
            },
            env: {
                node: true,
            },
        },
        {
            files: ['frontend/src/types.ts'],
            rules: {
                'posthog/no-survey-string-constants': 'off',
            },
        },
    ],
}
