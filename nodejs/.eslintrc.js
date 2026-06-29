module.exports = {
    root: true,
    parser: '@typescript-eslint/parser',
    parserOptions: {
        sourceType: 'module',
        tsconfigRootDir: __dirname,
        project: ['./tsconfig.eslint.json'],
    },
    plugins: ['@typescript-eslint', 'no-only-tests'],
    extends: [
        'plugin:@typescript-eslint/recommended',
        'plugin:@eslint-community/eslint-comments/recommended',
        'prettier',
    ],
    ignorePatterns: ['bin', 'dist', 'node_modules', 'src/common/config/idl'],
    rules: {
        'no-restricted-syntax': [
            'error',
            {
                selector: 'CallExpression[callee.object.name="JSON"][callee.property.name="parse"]',
                message: 'Use parseJSON from src/common/utils/json-parse instead of JSON.parse for better performance',
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
            },
        ],
        '@typescript-eslint/explicit-function-return-type': 'off',
        '@typescript-eslint/no-non-null-assertion': 'off',
        '@typescript-eslint/no-require-imports': 'off',
        '@typescript-eslint/no-explicit-any': 'off',
        'require-await': 'off',
        '@typescript-eslint/require-await': 'error',
        '@typescript-eslint/await-thenable': 'error',
        '@typescript-eslint/no-floating-promises': 'error',
        '@typescript-eslint/no-misused-promises': ['error', { checksVoidReturn: false }],
        '@typescript-eslint/no-empty-object-type': ['error', { allowInterfaces: 'with-single-extends' }],
        curly: 'error',
        'no-fallthrough': 'warn',
        'no-restricted-globals': [
            'error',
            {
                name: 'fetch',
                message: 'Use the request util from ~/common/utils/request instead of the global fetch',
            },
        ],
        'no-restricted-imports': [
            'error',
            {
                paths: [
                    {
                        name: 'node-fetch',
                        message: 'Use the request util from ~/common/utils/request instead of node-fetch',
                    },
                    {
                        name: 'undici',
                        message: 'Use the request util from ~/common/utils/request instead of undici',
                    },
                ],
                patterns: [
                    {
                        group: ['fetch'],
                        message: 'Use the request util from ~/common/utils/request instead of importing fetch directly',
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
        {
            // Ingestion is standardized on the ~/ alias. Ban parent-relative
            // (../) imports so the structure stays codemod-friendly through future moves; keep ./ siblings.
            // Overrides replace rule options, so the global fetch/node-fetch/undici bans are repeated here.
            files: ['src/ingestion/**/*.ts'],
            rules: {
                'no-restricted-imports': [
                    'error',
                    {
                        paths: [
                            {
                                name: 'node-fetch',
                                message: 'Use the request util from ~/common/utils/request instead of node-fetch',
                            },
                            {
                                name: 'undici',
                                message: 'Use the request util from ~/common/utils/request instead of undici',
                            },
                        ],
                        patterns: [
                            {
                                group: ['fetch'],
                                message:
                                    'Use the request util from ~/common/utils/request instead of importing fetch directly',
                            },
                            {
                                group: ['../*', '../**'],
                                message:
                                    'Within src/ingestion, import via the ~/ alias instead of parent-relative (../) paths.',
                            },
                        ],
                    },
                ],
            },
        },
    ],
    root: true,
    reportUnusedDisableDirectives: true,
}
