module.exports = {
    env: {
        browser: true,
        es6: true,
    },
    settings: {
        react: {
            version: 'detect',
        },
    },
    extends: ['eslint:recommended', 'plugin:react/recommended'],
    globals: {
        Atomics: 'readonly',
        SharedArrayBuffer: 'readonly',
    },
    parser: 'babel-eslint',
    parserOptions: {
        ecmaFeatures: {
            jsx: true,
        },
        ecmaVersion: 2018,
        sourceType: 'module',
    },
    plugins: ['prettier', 'react'],
    rules: {
        'react/prop-types': [0],
        'react/no-unescaped-entities': [0],
        'no-unused-vars': ['error', { ignoreRestSiblings: true }],
    },
}
