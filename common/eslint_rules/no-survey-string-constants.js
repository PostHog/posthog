/**
 * @type {import('eslint').Rule.RuleModule}
 */
module.exports = {
    meta: {
        type: 'problem',
        docs: {
            description:
                'Disallow specific hardcoded strings related to survey events and properties. Recommends and autofixes using enums from types.ts.',
            category: 'Best Practices',
            recommended: 'warn',
            url: 'https://github.com/PostHog/posthog/blob/master/common/eslint_rules/no-survey-string-constants.js', // Optional: Add a URL to rule documentation
        },
        fixable: 'code', // Enable autofixing
        schema: [], // No options for this rule
    },
    create: function (context) {
        // Lowercase for case-insensitive matching of event names
        // eslint-disable-next-line posthog/no-survey-string-constants
        const forbiddenEventStrings = ['survey sent', 'survey shown', 'survey dismissed']
        // Case-sensitive pattern for properties starting with $survey_
        const forbiddenPropertyPattern = /^\$survey_/

        const eventStringToEnum = {
            'survey sent': 'SurveyEventName.SENT',
            'survey shown': 'SurveyEventName.SHOWN',
            'survey dismissed': 'SurveyEventName.DISMISSED',
        }

        const propertyStringToEnum = {
            $survey_id: 'SurveyEventProperties.SURVEY_ID',
            $survey_response: 'SurveyEventProperties.SURVEY_RESPONSE',
        }

        // Function to check a string value (from Literal or TemplateElement)
        // The `fixer` argument is only provided when called from the Literal visitor
        function checkStringValue(node, value, fixer) {
            if (typeof value !== 'string') {
                return
            }
            const lowerCaseValue = value.toLowerCase()
            let reportObject = null

            // Check for exact forbidden event strings (case-insensitive)
            if (forbiddenEventStrings.includes(lowerCaseValue)) {
                const enumString = eventStringToEnum[lowerCaseValue]
                reportObject = {
                    node: node,
                    message: `Avoid hardcoding survey event names like '${value}'. Import from 'SurveyEventName' in 'frontend/src/types.ts' instead.`,
                }
                if (fixer && enumString) {
                    // Only add fix if called with a fixer (i.e., from Literal visitor) and we have a mapping
                    reportObject.fix = function (fixerInstance) {
                        // Replace the literal node (including quotes) with the enum member
                        return fixerInstance.replaceText(node, enumString)
                    }
                }
            }

            // Check for the forbidden property pattern (case-sensitive)
            else if (forbiddenPropertyPattern.test(value)) {
                const enumString = propertyStringToEnum[value]
                // Find the specific match to report it more accurately
                const match = value.match(forbiddenPropertyPattern)
                if (match) {
                    reportObject = {
                        node: node,
                        message: `Avoid hardcoding survey properties starting with '$survey_'. Found '${match[0]}'. Import from 'SurveyEventProperties' in 'frontend/src/types.ts' instead.`,
                    }
                    if (fixer && enumString) {
                        // Only add fix if called with a fixer (i.e., from Literal visitor) and we have an exact mapping for the whole string
                        reportObject.fix = function (fixerInstance) {
                            // Replace the literal node (including quotes) with the enum member
                            return fixerInstance.replaceText(node, enumString)
                        }
                    }
                }
            }
            // Check for the pattern appearing within the string part (e.g., in template literals)
            else {
                const substringMatch = value.match(/properties\.\$survey_/)
                if (substringMatch) {
                    reportObject = {
                        node: node,
                        message: `Avoid hardcoding survey property access like '${substringMatch[0]}'. Import from 'SurveyEventProperties' in 'frontend/src/types.ts' instead.`,
                        // No fix for substring matches within template literals - too complex
                    }
                }
            }

            if (reportObject) {
                context.report(reportObject)
            }
        }

        return {
            Literal: function (node) {
                // Pass the fixer only for Literals
                checkStringValue(node, node.value, true)
            },
            TemplateLiteral: function (node) {
                // Check each quasi (static part) of the template literal
                node.quasis.forEach((quasi) => {
                    // Do not pass the fixer for template parts
                    checkStringValue(quasi, quasi.value.cooked, false)
                })
            },
        }
    },
}
