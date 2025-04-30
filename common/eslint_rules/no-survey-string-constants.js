/**
 * @type {import('eslint').Rule.RuleModule}
 */
module.exports = {
    meta: {
        type: 'problem',
        docs: {
            description: 'Disallow specific hardcoded strings related to survey events and properties.',
            category: 'Best Practices',
            recommended: 'warn',
            url: 'https://github.com/PostHog/posthog/blob/master/common/eslint_rules/no-survey-string-constants.js', // Optional: Add a URL to rule documentation
        },
        fixable: null, // We are not providing autofix suggestions
        schema: [], // No options for this rule
    },
    create: function (context) {
        // Lowercase for case-insensitive matching of event names
        // eslint-disable-next-line posthog/no-survey-string-constants
        const forbiddenEventStrings = ['survey sent', 'survey shown', 'survey dismissed']
        // Case-sensitive pattern for properties starting with $survey_
        const forbiddenPropertyPattern = /^\\$survey_/

        // Function to check a string value (from Literal or TemplateElement)
        function checkStringValue(node, value) {
            if (typeof value !== 'string') {
                return
            }
            const lowerCaseValue = value.toLowerCase()

            // Check for exact forbidden event strings (case-insensitive)
            if (forbiddenEventStrings.includes(lowerCaseValue)) {
                context.report({
                    node: node,
                    message: `Avoid hardcoding survey event names like '${value}'. Import from 'SurveyEventName' in 'frontend/src/types.ts' instead.`,
                })
            }

            // Check for the forbidden property pattern (case-sensitive)
            // We need to check substrings within the template literal parts
            if (forbiddenPropertyPattern.test(value)) {
                // Find the specific match to report it more accurately if needed
                const match = value.match(forbiddenPropertyPattern)
                if (match) {
                    context.report({
                        node: node,
                        message: `Avoid hardcoding survey properties starting with '$survey_'. Found '${match[0]}'. Import from 'SurveyEventProperties' in 'frontend/src/types.ts' instead.`,
                    })
                }
            } else {
                // Also check for the pattern appearing within the string part
                // e.g. `AND properties.$survey_id = ...`
                const substringMatch = value.match(/properties\.\$survey_/)
                if (substringMatch) {
                    context.report({
                        node: node,
                        message: `Avoid hardcoding survey property access like '${substringMatch[0]}'. Import from 'SurveyEventProperties' in 'frontend/src/types.ts' instead.`,
                    })
                }
            }
        }

        return {
            Literal: function (node) {
                checkStringValue(node, node.value)
            },
            TemplateLiteral: function (node) {
                // Check each quasi (static part) of the template literal
                node.quasis.forEach((quasi) => {
                    checkStringValue(quasi, quasi.value.cooked)
                })
            },
        }
    },
}
