// Run with: node --test .github/scripts/preview-flags.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const { CONSTANTS_PATH, detectPreviewFlags } = require('./preview-flags')

const constantsSource = `export const FEATURE_FLAGS = {
    EXISTING_FLAG: 'existing-flag', // owner: @someone
    OTHER_FLAG: 'other-flag',
}
`

const cases = [
    {
        name: 'maps an added FEATURE_FLAGS reference to its key',
        files: [
            { filename: 'frontend/src/scenes/a.tsx', patch: '+    if (featureFlags[FEATURE_FLAGS.EXISTING_FLAG]) {' },
        ],
        expected: ['existing-flag'],
    },
    {
        name: 'ignores references on removed and context lines',
        files: [
            {
                filename: 'frontend/src/scenes/a.tsx',
                patch: '-    FEATURE_FLAGS.EXISTING_FLAG\n     FEATURE_FLAGS.OTHER_FLAG',
            },
        ],
        expected: [],
    },
    {
        name: 'picks up a new constant entry',
        files: [{ filename: CONSTANTS_PATH, patch: "+    BRAND_NEW: 'brand-new', // owner: @someone" }],
        expected: ['brand-new'],
    },
    {
        name: 'picks up a python literal key',
        files: [
            {
                filename: 'posthog/api/a.py',
                patch: '+    if posthoganalytics.feature_enabled("backend-flag", str(user.distinct_id)):',
            },
        ],
        expected: ['backend-flag'],
    },
    {
        name: 'adds keys from the PR body and drops invalid ones',
        body: 'Some text\nPreview flags: `body-flag`, $(rm -rf), Bad_Upper\n',
        files: [],
        expected: ['body-flag'],
    },
    {
        name: 'turns off the scan with Preview flags: none',
        body: 'Preview flags: none',
        files: [{ filename: 'frontend/src/scenes/a.tsx', patch: '+FEATURE_FLAGS.EXISTING_FLAG' }],
        expected: [],
    },
]

test.describe('detectPreviewFlags', () => {
    for (const { name, body, files, expected } of cases) {
        test(name, () => {
            assert.deepEqual(detectPreviewFlags({ body, files, constantsSource }), expected)
        })
    }
})
