const iterationMethods = new Set(['map', 'flatMap', 'forEach', 'filter', 'some', 'every'])

function rootName(node) {
    while (node?.type === 'MemberExpression') {
        node = node.object
    }
    return node?.type === 'Identifier' ? node.name : undefined
}

function isKeyLookup(callback) {
    const parameter = callback?.params?.[0]
    const predicate = callback?.body
    if (parameter?.type !== 'Identifier' || predicate?.type !== 'BinaryExpression' || predicate.operator !== '===') {
        return false
    }
    return [predicate.left, predicate.right].some(
        (side) =>
            side.type === 'MemberExpression' && side.object.type === 'Identifier' && side.object.name === parameter.name
    )
}

function isDeclaredInside(context, node, name, ancestor) {
    for (let scope = context.sourceCode.getScope(node); scope; scope = scope.upper) {
        const variable = scope.set.get(name)
        if (variable) {
            return variable.defs.some(
                (definition) =>
                    definition.name.range[0] >= ancestor.range[0] && definition.name.range[1] <= ancestor.range[1]
            )
        }
    }
    return false
}

function iterationFor(node) {
    for (let ancestor = node.parent; ancestor; ancestor = ancestor.parent) {
        if (['ArrowFunctionExpression', 'FunctionExpression', 'FunctionDeclaration'].includes(ancestor.type)) {
            const call = ancestor.parent
            return call?.type === 'CallExpression' &&
                call.arguments[0] === ancestor &&
                call.callee.type === 'MemberExpression' &&
                !call.callee.computed &&
                iterationMethods.has(call.callee.property.name)
                ? ancestor
                : undefined
        }
    }
    return undefined
}

function lookupReceiver(node) {
    const callee = node.callee
    return callee.type === 'MemberExpression' &&
        !callee.computed &&
        ['find', 'findIndex'].includes(callee.property.name) &&
        isKeyLookup(node.arguments[0])
        ? rootName(callee.object)
        : undefined
}

export default {
    meta: { name: 'react-performance' },
    rules: {
        'no-repeated-array-lookup': {
            meta: {
                type: 'suggestion',
                schema: [],
                messages: {
                    repeatedLookup:
                        'This key lookup scans the same collection for each item. Build an index before the iteration and preserve duplicate-key behavior.',
                },
            },
            create(context) {
                return {
                    CallExpression(node) {
                        const receiver = lookupReceiver(node)
                        const iteration = receiver && iterationFor(node)
                        if (iteration && !isDeclaredInside(context, node, receiver, iteration)) {
                            context.report({ node, messageId: 'repeatedLookup' })
                        }
                    },
                }
            },
        },
    },
}
