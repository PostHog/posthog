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
    extends: ['plugin:@typescript-eslint/recommended', 'plugin:react/recommended', 'prettier'],
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
    plugins: ['prettier', 'react', 'react-hooks', 'cypress', '@typescript-eslint'],
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
        'react-hooks/rules-of-hooks': 'warn',
        'react-hooks/exhaustive-deps': 'warn',
        'no-unused-vars': ['error', { ignoreRestSiblings: true }],
        '@typescript-eslint/explicit-function-return-type': 'off',
        '@typescript-eslint/explicit-module-boundary-types': 'off',
        '@typescript-eslint/no-empty-function': 'off',
        '@typescript-eslint/no-inferrable-types': 'off',
        '@typescript-eslint/ban-ts-comment': 'off',
        'no-shadow': 'error',
        '@typescript-eslint/no-non-null-assertion': 'error',
        curly: 'error',
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
}
