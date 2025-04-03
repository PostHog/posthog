module.exports = {
    meta: {
        type: 'problem',
        docs: {
            description:
                "Disallow use of jest's .toBeDefined() inside expect() calls. This is because expect(null).toBeDefined() will succeed, so if a function returns null this will count as being defined, which is probably not what you intended.",
            category: 'Best Practices',
            recommended: true,
        },
        messages: {
            noToBeDefined: 'Do not use .toBeDefined() in tests, use .toBeTruthy() or .not.toBeUndefined() instead.',
        },
        schema: [],
    },

    create(context) {
        return {
            CallExpression(node) {
                // Matches expect(...).toBeDefined()
                if (
                    node.callee?.type === 'MemberExpression' &&
                    node.callee.property?.name === 'toBeDefined' &&
                    node.callee.object?.type === 'CallExpression' &&
                    node.callee.object.callee?.name === 'expect'
                ) {
                    context.report({
                        node: node.callee.property,
                        messageId: 'noToBeDefined',
                    })
                }
            },
        }
    },
}
