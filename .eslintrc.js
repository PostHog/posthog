/* eslint-disable @typescript-eslint/no-var-requires */
/* global module */

module.exports = {
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
    extends: ['plugin:@typescript-eslint/recommended', 'plugin:react/recommended', 'prettier/@typescript-eslint'],
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
    plugins: ['prettier', 'react', 'cypress', '@typescript-eslint'],
    rules: {
        'react/prop-types': [0],
        'react/no-unescaped-entities': [0],
        'no-unused-vars': ['error', { ignoreRestSiblings: true }],
        '@typescript-eslint/explicit-function-return-type': 'off',
        '@typescript-eslint/explicit-module-boundary-types': 'off',
        '@typescript-eslint/no-empty-function': 'off',
        '@typescript-eslint/no-inferrable-types': 'off',
    },
    overrides: [
        {
            // enable the rule specifically for TypeScript files
            files: ['*.ts', '*.tsx'],
            rules: {
                '@typescript-eslint/explicit-function-return-type': [
                    'error',
                    {
                        allowExpressions: true,
                    },
                ],
                '@typescript-eslint/explicit-module-boundary-types': ['error'],
            },
        },
        {
            files: ['*.js'],
            rules: {
                'typescript/no-var-requires': 'off',
            },
        },
    ],
}
