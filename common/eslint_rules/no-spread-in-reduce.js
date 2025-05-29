module.exports = {
    meta: {
        type: 'problem',
        docs: {
            description: 'Disallow spread operator in reduce callbacks for performance',
            category: 'Best Practices',
            recommended: true,
        },
        schema: [],
        messages: {
            noSpreadInReduce:
                'Avoid using spread operator in reduce accumulator - it creates a new object on every iteration. Assign to the accumulator directly instead.',
        },
    },
    create(context) {
        return {
            CallExpression(node) {
                // Check if it's a reduce call
                if (node.callee.property?.name === 'reduce') {
                    const callback = node.arguments[0]

                    // Handle arrow functions and regular functions
                    const fnBody = callback.body || callback

                    // Look for spread operator in the return object
                    if (fnBody.type === 'ObjectExpression') {
                        const hasSpread = fnBody.properties.some((prop) => prop.type === 'SpreadElement')
                        if (hasSpread) {
                            context.report({
                                node,
                                messageId: 'noSpreadInReduce',
                            })
                        }
                    } else if (fnBody.type === 'BlockStatement') {
                        // For functions with blocks, look for return statements with spread
                        const returnStmt = fnBody.body.find((stmt) => stmt.type === 'ReturnStatement')
                        if (returnStmt?.argument?.type === 'ObjectExpression') {
                            const hasSpread = returnStmt.argument.properties.some(
                                (prop) => prop.type === 'SpreadElement'
                            )
                            if (hasSpread) {
                                context.report({
                                    node,
                                    messageId: 'noSpreadInReduce',
                                })
                            }
                        }
                    }
                }
            },
        }
    },
}
