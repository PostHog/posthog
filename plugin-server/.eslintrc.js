module.exports = {
    root: true,
    parser: '@typescript-eslint/parser',
    parserOptions: {
        sourceType: 'module',
        tsconfigRootDir: __dirname,
        project: ['./tsconfig.eslint.json'],
    },
    plugins: ['@typescript-eslint', 'simple-import-sort', 'prettier', 'no-only-tests'],
    extends: ['plugin:@typescript-eslint/recommended', 'plugin:eslint-comments/recommended', 'prettier'],
    ignorePatterns: ['bin', 'dist', 'node_modules', 'src/config/idl'],
    rules: {
        'no-only-tests/no-only-tests': 'error',
        'simple-import-sort/imports': 'error',
        'simple-import-sort/exports': 'error',
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
    },
    overrides: [
        {
            files: ['**/__tests__/**/*.ts', 'src/celery/**/*.ts'],
            rules: {
                '@typescript-eslint/no-explicit-any': 'off',
            },
        },
    ],
    root: true,
    reportUnusedDisableDirectives: true,
}
