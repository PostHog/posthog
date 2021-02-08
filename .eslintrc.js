module.exports = {
    parser: '@typescript-eslint/parser',
    plugins: ['@typescript-eslint', 'simple-import-sort'],
    extends: ['plugin:@typescript-eslint/recommended', 'prettier', 'prettier/@typescript-eslint', 'prettier/react'],
    ignorePatterns: ['bin', 'dist', 'node_modules'],
    rules: {
        'simple-import-sort/imports': 'error',
        'simple-import-sort/exports': 'error',
        '@typescript-eslint/no-unused-vars': 'off',
        '@typescript-eslint/explicit-function-return-type': 'off',
        '@typescript-eslint/no-non-null-assertion': 'off',
        '@typescript-eslint/no-var-requires': 'off',
        '@typescript-eslint/no-explicit-any': 'off',
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
}
