module.exports = {
    root: true,
    parser: '@typescript-eslint/parser',
    // Keep ESLint untyped for directive checks and proto cleanup; Oxlint handles types without the V8 heap cost.
    parserOptions: {
        sourceType: 'module',
        project: false,
        projectService: false,
    },
    plugins: ['@typescript-eslint'],
    extends: ['plugin:@eslint-community/eslint-comments/recommended'],
    reportUnusedDisableDirectives: false,
    ignorePatterns: [
        'bin',
        'dist',
        'node_modules',
        'src/common/config/idl',
        'src/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub-sidecar',
        '**/dev/**',
    ],
    overrides: [
        {
            files: ['**/*.ts', '**/*.tsx', '**/*.mts', '**/*.cts'],
        },
        {
            files: ['src/common/generated/**/*.ts'],
            reportUnusedDisableDirectives: true,
        },
    ],
}
