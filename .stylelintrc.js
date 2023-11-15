module.exports = {
    extends: 'stylelint-config-standard-scss',
    rules: {
        'no-descending-specificity': null,
        'number-max-precision': 5,
        'value-keyword-case': [
            'lower',
            {
                // CSS Color Module Level 3 says currentColor, Level 4 candidate says currentcolor
                // Sticking to Level 3 for now
                camelCaseSvgKeywords: true,
            },
        ],
        // Sadly Safari only started supporting the range syntax of media queries in 2023, so let's switch to that
        // ('context' value) in 2024, once support is better https://caniuse.com/?search=range%20context
        'media-feature-range-notation': 'prefix',
        'selector-class-pattern': [
            '^[A-Za-z0-9_-]+(__[A-Za-z0-9_-]+)?(--[A-Za-z0-9-]+)?$',
            {
                message: 'Expected class selector to match Block__Element--Modifier or plain snake-case',
            },
        ],
        'selector-id-pattern': [
            '^[A-Za-z0-9_-]+(__[A-Za-z0-9_-]+)?(--[A-Za-z0-9_-]+)?$',
            {
                message: 'Expected id selector to match Block__Element--Modifier or plain kebak-case',
            },
        ],
        'keyframes-name-pattern': [
            '^[A-Za-z0-9_-]+__[A-Za-z0-9_-]+$',
            {
                message: 'Expected keyframe name to match Block__Animation',
            },
        ],
        'scss/dollar-variable-pattern': [
            '^[A-Za-z_]+[A-Za-z0-9_-]+$',
            {
                message: 'Expected variable to match kebab-case or snake_case',
            },
        ],
        'scss/operator-no-newline-after': null,
        'scss/at-extend-no-missing-placeholder': null,
        'scss/comment-no-empty': null,
    },
}
