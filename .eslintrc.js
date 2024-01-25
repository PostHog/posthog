/* global module */

const env = {
    browser: true,
    es6: true,
    'cypress/globals': true,
}

const globals = {
    Atomics: 'readonly',
    SharedArrayBuffer: 'readonly',
}

module.exports = {
    ignorePatterns: ['node_modules', 'plugin-server', 'cypress'],
    env,
    settings: {
        react: {
            version: 'detect',
        },
        'import/resolver': {
            node: {
                paths: ['eslint-rules'], // Add the directory containing your custom rules
                extensions: ['.js', '.jsx', '.ts', '.tsx'], // Ensure ESLint resolves both JS and TS files
            },
        },
    },
    extends: [
        'eslint:recommended',
        'plugin:@typescript-eslint/recommended-type-checked',
        'plugin:react/recommended',
        'plugin:eslint-comments/recommended',
        'plugin:storybook/recommended',
        'plugin:compat/recommended',
        'prettier', // Disables any formatting rules to let prettier do its job
    ],
    globals,
    parser: '@typescript-eslint/parser',
    parserOptions: {
        project: 'tsconfig.json',
    },
    plugins: [
        'react',
        'cypress',
        '@typescript-eslint',
        'no-only-tests',
        'jest',
        'compat',
        'posthog',
        'simple-import-sort',
        'import',
    ],
    rules: {
        // PyCharm always adds curly braces, I guess vscode doesn't, PR reviewers often complain they are present on props that don't need them
        // let's save the humans time and let the machines do the work
        // "never" means if the prop does not need the curly braces, they will be removed/errored
        // see https://github.com/jsx-eslint/eslint-plugin-react/blob/master/docs/rules/jsx-curly-brace-presence.md
        'react/jsx-curly-brace-presence': ['error', { props: 'never', children: 'never', propElementValues: 'always' }],
        'no-console': ['error', { allow: ['warn', 'error'] }],
        'no-debugger': 'error',
        'no-only-tests/no-only-tests': 'error',
        'simple-import-sort/imports': 'error',
        'simple-import-sort/exports': 'error',
        'react/prop-types': [0],
        'react/react-in-jsx-scope': [0],
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
        '@typescript-eslint/prefer-ts-expect-error': 'error',
        '@typescript-eslint/no-empty-function': 'off',
        '@typescript-eslint/no-inferrable-types': 'off',
        '@typescript-eslint/ban-ts-comment': 'off',
        '@typescript-eslint/require-await': 'off', // TODO: Enable - this rule is useful, but doesn't have an autofix
        '@typescript-eslint/no-unsafe-assignment': 'off',
        '@typescript-eslint/no-unsafe-member-access': 'off',
        '@typescript-eslint/no-unsafe-enum-comparison': 'off',
        '@typescript-eslint/no-unsafe-argument': 'off',
        '@typescript-eslint/no-unsafe-return': 'off',
        '@typescript-eslint/no-unsafe-call': 'off',
        '@typescript-eslint/no-explicit-any': 'off',
        '@typescript-eslint/restrict-template-expressions': 'off',
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
        curly: 'error',
        'no-restricted-imports': [
            'error',
            {
                paths: [
                    {
                        name: 'dayjs',
                        message: 'Do not directly import dayjs. Only import the dayjs exported from lib/dayjs.',
                    },
                    {
                        name: '@ant-design/icons',
                        message: 'Please use icons from the @posthog/icons package instead',
                    },
                    {
                        name: 'antd',
                        importNames: ['Card', 'Col', 'Row', 'Alert', 'Tooltip'],
                        message: 'please use the Lemon equivalent instead',
                    },
                ],
            },
        ],
        'react/forbid-dom-props': [
            'error',
            {
                forbid: [
                    {
                        propName: 'style',
                        message:
                            'style should be avoided in favor of utility CSS classes - see https://storybook.posthog.net/?path=/docs/lemon-ui-utilities--overview',
                    },
                ],
            },
        ],
        'posthog/warn-elements': [
            'warn',
            {
                forbid: [
                    {
                        element: 'Divider',
                        message: 'use <LemonDivider> instead',
                    },
                    {
                        element: 'Button',
                        message: 'use <LemonButton> instead',
                    },
                    {
                        element: 'Input',
                        message: 'use <LemonInput> instead',
                    },
                    {
                        element: 'Skeleton',
                        message: 'use <LemonSkeleton> instead',
                    },
                    {
                        element: 'Modal',
                        message: 'use <LemonModal> or `<LemonDialog> instead',
                    },
                    {
                        element: 'Select',
                        message: 'use <LemonSelect> instead',
                    },
                    {
                        element: 'LemonButtonWithDropdown',
                        message: 'use <LemonMenu> with a <LemonButton> child instead',
                    },
                ],
            },
        ],
        'react/forbid-elements': [
            'error',
            {
                forbid: [
                    {
                        element: 'Layout',
                        message: 'use utility classes instead',
                    },
                    {
                        element: 'Tabs',
                        message: 'use <LemonTabs> instead',
                    },
                    {
                        element: 'Space',
                        message: 'use flex or space utility classes instead',
                    },
                    {
                        element: 'Spin',
                        message: 'use Spinner instead',
                    },
                    {
                        element: 'Badge',
                        message: 'use LemonBadge instead',
                    },
                    {
                        element: 'InputNumber',
                        message: 'use LemonInput with type="number" instead',
                    },
                    {
                        element: 'Collapse',
                        message: 'use <LemonCollapse> instead',
                    },
                    {
                        element: 'Checkbox',
                        message: 'use <LemonCheckbox> instead',
                    },
                    {
                        element: 'MonacoEditor',
                        message: 'use <CodeEditor> instead',
                    },
                    {
                        element: 'Typography',
                        message: 'use utility classes instead',
                    },
                    {
                        element: 'Input.TextArea',
                        message: 'use <LemonTextArea> instead',
                    },
                    {
                        element: 'ReactMarkdown',
                        message: 'use <LemonMarkdown> instead',
                    },
                    {
                        element: 'a',
                        message: 'use <Link> instead',
                    },
                    {
                        element: 'Tag',
                        message: 'use <LemonTag> instead',
                        element: 'Alert',
                        message: 'use <LemonBanner> instead',
                    },
                    {
                        element: 'ReactJson',
                        message: 'use <JSONViewer> for dark mode support instead',
                    },
                ],
            },
        ],
        'no-constant-binary-expression': 'error',
        'no-constant-condition': 'off',
        'no-prototype-builtins': 'off',
        'no-irregular-whitespace': 'off',
        'no-useless-rename': 'error',
        'import/no-restricted-paths': [
            'error',
            {
                zones: [
                    {
                        target: './frontend/**',
                        from: './ee/frontend/**',
                        message:
                            "EE licensed TypeScript should only be accessed via the posthogEE objects. Use `import posthogEE from '@posthog/ee/exports'`",
                    },
                ],
            },
        ],
    },
    overrides: [
        {
            files: ['**/test/**/*', '**/*.test.*'],
            env: {
                ...env,
                node: true,
                'jest/globals': true,
            },
            globals: {
                ...globals,
                given: 'readonly',
            },
            rules: {
                // The below complains needlessly about expect(api.createInvite).toHaveBeenCalledWith(...)
                '@typescript-eslint/unbound-method': 'off',
            },
        },
        {
            files: ['*Type.ts', '*Type.tsx'], // Kea typegen output
            rules: {
                'no-restricted-imports': 'off',
                '@typescript-eslint/ban-types': 'off',
                'simple-import-sort/imports': 'off',
                'simple-import-sort/exports': 'off',
            },
        },
        {
            files: ['frontend/src/scenes/notebooks/Nodes/*'], // Notebooks code weirdly relies on its order of sorting
            rules: {
                'simple-import-sort/imports': 'off',
                'simple-import-sort/exports': 'off',
            },
        },
        {
            files: ['*.js'],
            rules: {
                '@typescript-eslint/no-var-requires': 'off',
                '@typescript-eslint/explicit-function-return-type': 'off',
                '@typescript-eslint/explicit-module-boundary-types': 'off',
            },
        },
        {
            files: ['*.mjs'],
            rules: {
                '@typescript-eslint/no-var-requires': 'off',
                '@typescript-eslint/explicit-function-return-type': 'off',
                '@typescript-eslint/explicit-module-boundary-types': 'off',
                '@typescript-eslint/no-misused-promises': 'off',
                'no-console': 'off',
            },
            globals: { ...globals, process: 'readonly' },
        },
        {
            files: 'eslint-rules/**/*',
            rules: {
                '@typescript-eslint/no-var-requires': 'off',
            },
            env: {
                node: true,
            },
        },
    ],
    reportUnusedDisableDirectives: true,
}
