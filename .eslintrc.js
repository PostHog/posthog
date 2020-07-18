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
    extends: [
        'plugin:react/recommended',
        'plugin:@typescript-eslint/recommended',
        'prettier/@typescript-eslint',
        'plugin:prettier/recommended', // Enables eslint-plugin-prettier and eslint-config-prettier. This will display prettier errors as ESLint errors. Make sure this is always the last configuration in the extends array.
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
    },
    plugins: ['prettier', 'react', 'cypress', '@typescript-eslint'],
    rules: {
        'react/prop-types': [0],
        'react/no-unescaped-entities': [0],
        'no-unused-vars': ['error', { ignoreRestSiblings: true }],
        '@typescript-eslint/explicit-function-return-type': 'off',
        '@typescript-eslint/explicit-module-boundary-types': 'off',
        '@typescript-eslint/no-empty-function': 'off',
    },
    overrides: [
        {
            // enable the rule specifically for TypeScript files
            files: ['*.ts', '*.tsx'],
            rules: {
                '@typescript-eslint/explicit-function-return-type': ['error'],
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
