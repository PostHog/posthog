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
    ignorePatterns: ['node_modules', 'plugin-server'],
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
        'prettier',
    ],
    globals,
    parser: '@typescript-eslint/parser',
    parserOptions: {
        ecmaFeatures: {
            jsx: true,
        },
        ecmaVersion: 2018,
        sourceType: 'module',
        project: 'tsconfig.json'
    },
    plugins: ['prettier', 'react', 'cypress', '@typescript-eslint', 'no-only-tests', 'jest', 'compat', 'posthog'],
    rules: {
        'no-console': ['error', { allow: ['warn', 'error'] }],
        'no-debugger': 'error',
        'no-only-tests/no-only-tests': 'error',
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
        '@typescript-eslint/explicit-function-return-type': 'off',
        '@typescript-eslint/explicit-module-boundary-types': 'off',
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
                        importNames: ['Tooltip'],
                        message: 'Please use Tooltip from @posthog/lemon-ui instead.',
                    },
                ],
            },
        ],
        'react/forbid-dom-props': [
            'warn',
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
                        element: 'Row',
                        message:
                            'use flex utility classes instead, e.g. <Row align="middle"> could be <div className="flex items-center">',
                    },
                    {
                        element: 'Col',
                        message: 'use flex utility classes instead - most of the time can simply be a plain <div>',
                    },
                    {
                        element: 'Divider',
                        message: 'use <LemonDivider> instead',
                    },
                    {
                        element: 'Card',
                        message: 'use utility classes instead',
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
                    {
                        element: 'Tag',
                        message: 'use <LemonTag> instead',
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
                ],
            },
        ],
        'no-constant-binary-expression': 'error',
        'no-constant-condition': 'off',
        'no-prototype-builtins': 'off',
        'no-irregular-whitespace': 'off',
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
            }
        },
        {
            // disable these rules for files generated by kea-typegen
            files: ['*Type.ts', '*Type.tsx'],
            rules: {
                'no-restricted-imports': 'off',
                '@typescript-eslint/ban-types': ['off'],
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
