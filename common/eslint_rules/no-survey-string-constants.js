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

        const forbiddenEventStrings = ['survey sent', 'survey shown', 'survey dismissed']
        // Case-sensitive pattern for properties starting with $survey_
        // const forbiddenPropertyPattern = /^\$survey_/ // No longer needed directly

        const eventStringToEnum = {
            'survey sent': 'SurveyEventName.SENT',
            'survey shown': 'SurveyEventName.SHOWN',
            'survey dismissed': 'SurveyEventName.DISMISSED',
        }

        const propertyStringToEnum = {
            $survey_id: 'SurveyEventProperties.SURVEY_ID',
            $survey_response: 'SurveyEventProperties.SURVEY_RESPONSE',
            $survey_iteration: 'SurveyEventProperties.SURVEY_ITERATION',
        }

        // Function to check a string value (from Literal or TemplateElement)
        // The `fixer` argument is only provided when called from the Literal visitor
        function checkStringValue(node, value, fixer) {
            if (typeof value !== 'string') {
                return
            }
            const lowerCaseValue = value.toLowerCase()
            let reportObject = null

            if (fixer && node.type === 'Literal') {
                // --- Checks for Literal nodes (potential autofix) ---

                // Event check (unchanged logic)
                const eventMatch = forbiddenEventStrings.find((forbidden) => lowerCaseValue === forbidden)
                if (eventMatch) {
                    const enumString = eventStringToEnum[eventMatch]
                    reportObject = {
                        node: node,
                        message: `Avoid hardcoding survey event names like '${value}'. Import from 'SurveyEventName' in 'frontend/src/types.ts' instead.`,
                        fix: (fixerInstance) => fixerInstance.replaceText(node, enumString),
                    }
                }

                // Property check:
                // 1. Check if it's a known property for potential fixing
                const knownPropertyEnum = propertyStringToEnum[value]
                // 2. Check if it *starts* with $survey_ for general reporting
                const startsWithSurvey = /^\$survey_/.test(value)

                if (startsWithSurvey) {
                    // It starts with $survey_, so report it.
                    reportObject = {
                        node: node,
                        // Suggest adding to enum if not known, otherwise suggest importing
                        message: `Avoid hardcoding survey properties like '${value}'. ${
                            knownPropertyEnum
                                ? "Import from 'SurveyEventProperties' in 'frontend/src/types.ts' instead."
                                : "Consider adding it to 'SurveyEventProperties' and importing it."
                        }`,
                    }
                    // Add fix *only* if it's a known property
                    if (knownPropertyEnum) {
                        reportObject.fix = (fixerInstance) => fixerInstance.replaceText(node, knownPropertyEnum)
                    }
                }
            } else {
                // TemplateLiteral quasi checks
                // --- Checks for TemplateLiteral quasis (no autofix, substring checks) ---

                // Event check (substring check, unchanged)
                const foundEventString = forbiddenEventStrings.find((forbidden) => lowerCaseValue.includes(forbidden))
                if (foundEventString) {
                    reportObject = {
                        node: node, // Report against the quasi node
                        message: `Avoid hardcoding survey event names. Found '${foundEventString}' within template literal. Import from 'SurveyEventName' in 'frontend/src/types.ts' instead.`,
                    }
                }

                // Check for properties referenced like properties.$survey_
                const propertyAccessMatch = value.match(/properties\.\$survey_/)
                // Check for any other occurrence of $survey_
                const anySurveyPropertyMatch = !propertyAccessMatch && value.match(/\$survey_/)

                if (propertyAccessMatch) {
                    // Report properties.$survey_ found
                    reportObject = {
                        node: node,
                        message: `Avoid hardcoding survey property access like '${propertyAccessMatch[0]}'. Import from 'SurveyEventProperties' in 'frontend/src/types.ts' instead.`,
                    }
                } else if (anySurveyPropertyMatch) {
                    // Report any other $survey_ found (quoted or direct)
                    const matchedProperty = anySurveyPropertyMatch[0] // The matched '$survey_' string
                    reportObject = {
                        node: node,
                        message: `Avoid hardcoding survey properties starting with '$survey_'. Found '${matchedProperty}' within template literal. Import from 'SurveyEventProperties' in 'frontend/src/types.ts' instead or add it to the enum.`,
                    }
                }
            }

            if (reportObject) {
                context.report(reportObject)
            }
        }

        return {
            Literal: function (node) {
                // Pass true for fixer when checking Literals
                checkStringValue(node, node.value, true)
            },
            TemplateLiteral: function (node) {
                node.quasis.forEach((quasi) => {
                    // Pass false for fixer when checking TemplateElement quasis
                    checkStringValue(quasi, quasi.value.cooked, false)
                })
            },
        }
    },
}
