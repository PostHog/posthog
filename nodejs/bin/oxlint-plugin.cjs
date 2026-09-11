const eslintComments = require('@eslint-community/eslint-plugin-eslint-comments')

module.exports = {
    rules: {
        ...Object.fromEntries(
            Object.entries(eslintComments.rules).map(([name, rule]) => [
                name,
                {
                    ...rule,
                    create(context) {
                        const sourceCode = Object.create(context.sourceCode, {
                            getAllComments: {
                                value: () =>
                                    context.sourceCode.getAllComments().map((comment) => ({
                                        ...comment,
                                        value: comment.value.replace(/^(\s*)oxlint(?=-)/, '$1eslint'),
                                    })),
                            },
                        })
                        return rule.create(
                            Object.create(context, {
                                sourceCode: { value: sourceCode },
                                report: {
                                    value(descriptor) {
                                        // ESLint uses column -1 to keep directive checks outside the disabled range.
                                        // Oxlint requires valid columns; blanket disables are checked by lint.cjs.
                                        if (descriptor.loc?.start.column === -1) {
                                            descriptor = {
                                                ...descriptor,
                                                loc: {
                                                    ...descriptor.loc,
                                                    start: { ...descriptor.loc.start, column: 0 },
                                                },
                                            }
                                        }
                                        context.report(descriptor)
                                    },
                                },
                            })
                        )
                    },
                },
            ])
        ),
        'no-json-parse': {
            meta: { type: 'problem', schema: [] },
            create(context) {
                return {
                    'CallExpression[callee.object.name="JSON"][callee.property.name="parse"]'(node) {
                        context.report({
                            node,
                            message:
                                'Use parseJSON from src/common/utils/json-parse instead of JSON.parse for better performance',
                        })
                    },
                }
            },
        },
    },
}
