import js from '@eslint/js';
import tseslint from '@typescript-eslint/eslint-plugin';
import tsparser from '@typescript-eslint/parser';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import cypress from 'eslint-plugin-cypress';
import eslintComments from 'eslint-plugin-eslint-comments';
import storybook from 'eslint-plugin-storybook';
import compat from 'eslint-plugin-compat';
import posthog from 'eslint-plugin-posthog';
import simpleImportSort from 'eslint-plugin-simple-import-sort';
import importPlugin from 'eslint-plugin-import';
import unusedImports from 'eslint-plugin-unused-imports';
import reactGoogleTranslate from 'eslint-plugin-react-google-translate';
import jest from 'eslint-plugin-jest';
import globals from 'globals';

export default [
    // Global ignores
    {
        ignores: [
            'node_modules/**',
            '**/node_modules/**',
            'plugin-server/**',
            'rust/**',
            'livestream/**',
            'common/hogvm/typescript/**',
            'common/plugin_transpiler/**',
            'common/hogvm/__tests__/**/__snapshots__/**',
            'cypress/**/*.ts',
            '.eslintrc.js',
            'jest.config.ts',
            'common/hogvm/__tests__/__snapshots__/**',
            'common/hogvm/typescript/dist/**',
            'common/hogvm/typescript/jest.config.js',
            'common/plugin_transpiler/dist/**',
            'common/plugin_transpiler/build.mjs',
            '**/jest.config.js',
            '**/*LogicType.ts',
            '**/*.d.ts',
            '**/__snapshots__/*.snap',
            '.cursor/**',
            '.dagster/**',
            '.devcontainer/**',
            '.flox/**',
            '.ruff_cache/**',
            '.vscode/**',
            '.cache/**',
            'dist/**',
            'build/**',
            'dags/**',
            'funnel-udf/**',
            'patches/**',
            '**/__pycache__/**',
            '**/*.pyc',
            '**/*.pyo',
            '**/*.pyd',
            '**/*.py',
        ]
    },

    // Base JavaScript config
    js.configs.recommended,

    // Main configuration
    {
        languageOptions: {
            ecmaVersion: 'latest',
            sourceType: 'module',
            parser: tsparser,
            parserOptions: {
                project: true,
                tsconfigRootDir: import.meta.dirname,
                ecmaFeatures: {
                    jsx: true
                }
            },
            globals: {
                ...globals.browser,
                ...globals.es6,
                Atomics: 'readonly',
                SharedArrayBuffer: 'readonly'
            }
        },

        plugins: {
            '@typescript-eslint': tseslint,
            'react': react,
            'react-hooks': reactHooks,
            'cypress': cypress,
            'eslint-comments': eslintComments,
            'storybook': storybook,
            'compat': compat,
            'posthog': posthog,
            'simple-import-sort': simpleImportSort,
            'import': importPlugin,
            'unused-imports': unusedImports,
            'react-google-translate': reactGoogleTranslate
        },

        settings: {
            react: {
                version: 'detect'
            },
            'import/resolver': {
                node: {
                    paths: [
                        './common/eslint_rules',
                        '../common/eslint_rules',
                        '../../common/eslint_rules',
                        '../../../common/eslint_rules'
                    ],
                    extensions: ['.js', '.jsx', '.ts', '.tsx']
                }
            }
        },

        rules: {
            'react-hooks/rules-of-hooks': 'error',
            'react-hooks/exhaustive-deps': 'warn',
            'react/jsx-curly-brace-presence': ['error', { props: 'never', children: 'never', propElementValues: 'always' }],
            'no-console': ['error', { allow: ['warn', 'error'] }],
            'no-debugger': 'error',
            'simple-import-sort/imports': 'error',
            'simple-import-sort/exports': 'error',
            'react/prop-types': 'off',
            'react/react-in-jsx-scope': 'off',
            'react/no-unescaped-entities': 'off',
            'react/jsx-no-target-blank': 'off',
            'react/self-closing-comp': ['error', { component: true, html: true }],
            'unused-imports/no-unused-imports': 'error',
            'no-unused-vars': 'off',
            '@typescript-eslint/no-unused-vars': ['error', { ignoreRestSiblings: true, destructuredArrayIgnorePattern: '^_$' }],
            '@typescript-eslint/prefer-ts-expect-error': 'error',
            '@typescript-eslint/no-empty-function': 'off',
            '@typescript-eslint/no-inferrable-types': 'off',
            '@typescript-eslint/ban-ts-comment': 'off',
            '@typescript-eslint/require-await': 'off',
            '@typescript-eslint/no-unsafe-assignment': 'off',
            '@typescript-eslint/no-unsafe-member-access': 'off',
            '@typescript-eslint/no-unsafe-enum-comparison': 'off',
            '@typescript-eslint/no-unsafe-argument': 'off',
            '@typescript-eslint/no-unsafe-return': 'off',
            '@typescript-eslint/no-unsafe-call': 'off',
            '@typescript-eslint/no-explicit-any': 'off',
            '@typescript-eslint/restrict-template-expressions': 'off',
            '@typescript-eslint/explicit-function-return-type': ['error', { allowExpressions: true }],
            '@typescript-eslint/explicit-module-boundary-types': ['error', { allowArgumentsExplicitlyTypedAsAny: true }],
            'curly': 'error',
            'no-restricted-imports': ['error', {
                paths: [
                    { name: 'dayjs', message: 'Do not directly import dayjs. Only import the dayjs exported from lib/dayjs.' },
                    { name: 'chart.js', message: "Do not directly import chart.js. Only import the Chart and friends exported from lib/Chart." },
                    { name: 'chart.js/auto', message: "Do not directly import chart.js/auto. Only import the Chart and friends exported from lib/Chart." }
                ]
            }],
            'react/forbid-dom-props': ['error', {
                forbid: [{
                    propName: 'style',
                    message: 'style should be avoided in favor of utility CSS classes - see https://storybook.posthog.net/?path=/docs/lemon-ui-utilities--overview'
                }]
            }],
            'posthog/warn-elements': ['warn', {
                forbid: [
                    { element: 'Button', message: 'use <LemonButton> instead' },
                    { element: 'Input', message: 'use <LemonInput> instead' },
                    { element: 'Modal', message: 'use <LemonModal> or `<LemonDialog> instead' },
                    { element: 'Select', message: 'use <LemonSelect> instead' },
                    { element: 'LemonButtonWithDropdown', message: 'use <LemonMenu> with a <LemonButton> child instead' },
                    { element: 'Progress', message: 'use <LemonProgress> instead' }
                ]
            }],
            'react/forbid-elements': ['error', {
                forbid: [
                    { element: 'Layout', message: 'use utility classes instead' },
                    { element: 'Tabs', message: 'use <LemonTabs> instead' },
                    { element: 'Space', message: 'use flex or space utility classes instead' },
                    { element: 'Spin', message: 'use Spinner instead' },
                    { element: 'Badge', message: 'use LemonBadge instead' },
                    { element: 'InputNumber', message: 'use LemonInput with type="number" instead' },
                    { element: 'Collapse', message: 'use <LemonCollapse> instead' },
                    { element: 'Slider', message: 'use <LemonSlider> instead' },
                    { element: 'Checkbox', message: 'use <LemonCheckbox> instead' },
                    { element: 'MonacoEditor', message: 'use <CodeEditor> instead' },
                    { element: 'Typography', message: 'use utility classes instead' },
                    { element: 'Input.TextArea', message: 'use <LemonTextArea> instead' },
                    { element: 'ReactMarkdown', message: 'use <LemonMarkdown> instead' },
                    { element: 'a', message: 'use <Link> instead' },
                    { element: 'Tag', message: 'use <LemonTag> instead' },
                    { element: 'Alert', message: 'use <LemonBanner> instead' },
                    { element: 'ReactJson', message: 'use <JSONViewer> for dark mode support instead' },
                    { element: 'Radio', message: 'use <LemonRadio> instead' },
                    { element: 'Skeleton', message: 'use <LemonSkeleton> instead' },
                    { element: 'Divider', message: 'use <LemonDivider> instead' },
                    { element: 'Popconfirm', message: 'use <LemonDialog> instead' }
                ]
            }],
            'no-constant-binary-expression': 'error',
            'no-constant-condition': 'off',
            'no-prototype-builtins': 'off',
            'no-irregular-whitespace': 'off',
            'no-useless-rename': 'error',
            'import/no-restricted-paths': ['error', {
                zones: [{
                    target: './frontend/**',
                    from: './ee/frontend/**',
                    message: "EE licensed TypeScript should only be accessed via the posthogEE objects. Use `import posthogEE from '@posthog/ee/exports'`"
                }]
            }],
            'no-else-return': 'warn',
            'react-google-translate/no-conditional-text-nodes-with-siblings': 'warn',
            'react-google-translate/no-return-text-nodes': 'warn',
            'posthog/no-schema-index-import': 'error',
            'posthog/no-survey-string-constants': 'warn'
        }
    },

    // Test files configuration
    {
        files: ['**/test/**/*', '**/*.test.*'],
        plugins: {
            jest
        },
        languageOptions: {
            globals: {
                ...globals.browser,
                ...globals.jest,
                given: 'readonly',
                global: 'writable',
                module: 'writable'
            }
        },
        rules: {
            '@typescript-eslint/unbound-method': 'off',
            'jest/expect-expect': 'off',
            'jest/no-mocks-import': 'off',
            'jest/no-standalone-expect': 'off',
            'jest/no-export': 'off',
            'jest/no-conditional-expect': 'warn'
        }
    },

    // Notebook files
    {
        files: ['frontend/src/scenes/notebooks/Nodes/*'],
        rules: {
            'simple-import-sort/imports': 'off',
            'simple-import-sort/exports': 'off'
        }
    },

    // JavaScript files
    {
        files: ['*.js'],
        rules: {
            '@typescript-eslint/no-var-requires': 'off',
            '@typescript-eslint/explicit-function-return-type': 'off',
            '@typescript-eslint/explicit-module-boundary-types': 'off'
        }
    },

    // MJS files
    {
        files: ['*.mjs'],
        languageOptions: {
            globals: {
                ...globals.node
            }
        },
        rules: {
            '@typescript-eslint/no-var-requires': 'off',
            '@typescript-eslint/explicit-function-return-type': 'off',
            '@typescript-eslint/explicit-module-boundary-types': 'off',
            '@typescript-eslint/no-misused-promises': 'off',
            'no-console': 'off'
        }
    },

    // ESLint rules directory
    {
        files: ['./common/eslint_rules/*'],
        languageOptions: {
            globals: {
                ...globals.node
            }
        },
        rules: {
            '@typescript-eslint/no-var-requires': 'off',
            'posthog/no-survey-string-constants': 'off'
        }
    },

    // Types file
    {
        files: ['frontend/src/types.ts'],
        rules: {
            'posthog/no-survey-string-constants': 'off'
        }
    }
]; 