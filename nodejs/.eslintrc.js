module.exports = {
    root: true,
    parser: '@typescript-eslint/parser',
    parserOptions: {
        sourceType: 'module',
        tsconfigRootDir: __dirname,
        project: ['./tsconfig.eslint.json'],
    },
    plugins: ['@typescript-eslint', 'no-only-tests'],
    extends: ['plugin:@typescript-eslint/recommended', 'plugin:eslint-comments/recommended', 'prettier'],
    ignorePatterns: ['bin', 'dist', 'node_modules', 'src/config/idl'],
    rules: {
        'no-restricted-syntax': [
            'error',
            {
                selector: 'CallExpression[callee.object.name="JSON"][callee.property.name="parse"]',
                message: 'Use parseJSON from src/utils/json-parse instead of JSON.parse for better performance',
            },
        ],
        'no-only-tests/no-only-tests': 'error',
        'no-constant-binary-expression': 'error',
        'no-unused-vars': 'off',
        '@typescript-eslint/no-unused-vars': [
            'error',
            {
                ignoreRestSiblings: true,
                argsIgnorePattern: '^_',
                varsIgnorePattern: '^_',
                caughtErrorsIgnorePattern: '^_',
            },
        ],
        '@typescript-eslint/prefer-ts-expect-error': 'error',
        '@typescript-eslint/explicit-function-return-type': 'off',
        '@typescript-eslint/no-non-null-assertion': 'off',
        '@typescript-eslint/no-var-requires': 'off',
        '@typescript-eslint/no-explicit-any': 'off',
        'require-await': 'off',
        '@typescript-eslint/require-await': 'error',
        '@typescript-eslint/await-thenable': 'error',
        '@typescript-eslint/no-floating-promises': 'error',
        '@typescript-eslint/no-misused-promises': ['error', { checksVoidReturn: false }],
        curly: 'error',
        'no-fallthrough': 'warn',
        'no-restricted-globals': [
            'error',
            {
                name: 'fetch',
                message: 'Use the request util from ~/utils/request instead of the global fetch',
            },
        ],
        'no-restricted-imports': [
            'error',
            {
                paths: [
                    {
                        name: 'node-fetch',
                        message: 'Use the request util from ~/utils/request instead of node-fetch',
                    },
                    {
                        name: 'undici',
                        message: 'Use the request util from ~/utils/request instead of undici',
                    },
                ],
                patterns: [
                    {
                        group: ['fetch'],
                        message: 'Use the request util from ~/utils/request instead of importing fetch directly',
                    },
                ],
            },
        ],
    },
    overrides: [
        {
            files: ['**/tests/**/*.ts', 'src/celery/**/*.ts'],
            rules: {
                '@typescript-eslint/no-explicit-any': 'off',
                '@typescript-eslint/no-floating-promises': 'off',
            },
        },
    ],
    root: true,
    reportUnusedDisableDirectives: true,
}
