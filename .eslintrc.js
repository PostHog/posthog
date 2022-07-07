/* global module */
module.exports = {
    ignorePatterns: ['node_modules', 'plugin-server'],
    env: {
        browser: true,
        es6: true,
        'cypress/globals': true,
    },
    settings: {
        react: {
            version: 'detect',
        },
    },
    extends: [
        'plugin:@typescript-eslint/recommended',
        'plugin:react/recommended',
        'plugin:eslint-comments/recommended',
        'plugin:storybook/recommended',
        'prettier',
    ],
    globals: {
        Atomics: 'readonly',
        SharedArrayBuffer: 'readonly',
    },
    parser: '@typescript-eslint/parser',
    parserOptions: {
        ecmaFeatures: {
            jsx: true,
        },
        ecmaVersion: 2018,
        sourceType: 'module',
    },
    plugins: ['prettier', 'react', 'cypress', '@typescript-eslint', 'react-hooks'],
    rules: {
        'react/prop-types': [0],
        'react/no-unescaped-entities': [0],
        'react/jsx-no-target-blank': [0],
        'react/self-closing-comp': [
            'error',
            {
                component: true,
                html: true,
            },
        ],
        'no-unused-vars': 'off',
        '@typescript-eslint/no-unused-vars': [
            'error',
            {
                ignoreRestSiblings: true,
            },
        ],
        'react-hooks/rules-of-hooks': 'warn',
        'react-hooks/exhaustive-deps': 'warn',
        '@typescript-eslint/prefer-ts-expect-error': 'error',
        '@typescript-eslint/explicit-function-return-type': 'off',
        '@typescript-eslint/explicit-module-boundary-types': 'off',
        '@typescript-eslint/no-empty-function': 'off',
        '@typescript-eslint/no-inferrable-types': 'off',
        '@typescript-eslint/ban-ts-comment': 'off',
        '@typescript-eslint/no-non-null-assertion': 'error',
        curly: 'error',
        'no-restricted-imports': [
            'error',
            {
                paths: [
                    {
                        name: 'dayjs',
                        message: 'Do not directly import dayjs. Only import the dayjs exported from lib/dayjs.',
                    },
                ],
            },
        ],
    },
    overrides: [
        {
            // enable the rule specifically for TypeScript files
            files: ['*Type.ts', '*Type.tsx'],
            rules: {
                '@typescript-eslint/no-explicit-any': ['off'],
                '@typescript-eslint/ban-types': ['off'],
            },
        },
        {
            // enable the rule specifically for TypeScript files
            files: ['*.ts', '*.tsx'],
            rules: {
                '@typescript-eslint/no-explicit-any': ['off'],
                '@typescript-eslint/explicit-function-return-type': [
                    'error',
                    {
                        allowExpressions: true,
                    },
                ],
                '@typescript-eslint/explicit-module-boundary-types': [
                    'error',
                    {
                        allowArgumentsExplicitlyTypedAsAny: true,
                    },
                ],
            },
        },
        {
            files: ['*.js'],
            rules: {
                '@typescript-eslint/no-var-requires': 'off',
            },
        },
    ],
    reportUnusedDisableDirectives: true,
}
