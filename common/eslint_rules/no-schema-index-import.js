module.exports = {
    meta: {
        type: 'problem',
        docs: {
            description: 'Prevent direct imports from queries/schema/index.ts and ensure imports from specific schema files',
            category: 'Best Practices',
            recommended: true,
        },
        fixable: 'code',
        schema: [], // no options
    },
    create(context) {
        return {
            ImportDeclaration(node) {
                const importSource = node.source.value

                // Only check for imports from queries/schema/index.ts
                if (importSource.match(/\/queries\/schema(\/index)?$/)) {
                    context.report({
                        node,
                        message: 'Do not import directly from queries/schema. Import from queries/schema/schema-general instead to avoid Webpack/Sucrase enum export issues.',
                        fix(fixer) {
                            // Replace with schema-general.tsx
                            return fixer.replaceText(node.source, "'~/queries/schema/schema-general'")
                        }
                    })
                }
            }
        }
    }
} 