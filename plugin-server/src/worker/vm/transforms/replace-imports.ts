import { Hub } from '../../../types'
import { PluginGen } from './common'

export const replaceImports: PluginGen =
    (_: Hub, imports: Record<string, any> = {}, usedImports: Set<string>) =>
    ({ types: t }) => ({
        visitor: {
            ImportDeclaration: {
                exit(path: any) {
                    const { node } = path
                    const importSource = node.source.value
                    const importedVars = new Map<string, string>()

                    if (typeof imports[importSource] === 'undefined') {
                        throw new Error(
                            `Cannot import '${importSource}'! This package is not provided by PostHog in plugins.`
                        )
                    }

                    usedImports.add(importSource)

                    for (const specifier of node.specifiers) {
                        if (t.isImportSpecifier(specifier)) {
                            if (t.isStringLiteral(specifier.imported)) {
                                importedVars.set(specifier.local.name, specifier.imported.value)
                            } else {
                                importedVars.set(specifier.local.name, specifier.imported.name)
                            }
                        } else if (t.isImportDefaultSpecifier(specifier)) {
                            importedVars.set(specifier.local.name, 'default')
                        } else if (t.isImportNamespaceSpecifier(specifier)) {
                            importedVars.set(specifier.local.name, 'default')
                        }
                    }

                    path.replaceWith(
                        t.variableDeclaration(
                            'const',
                            Array.from(importedVars.entries()).map(([varName, sourceName]) => {
                                const importExpression = t.memberExpression(
                                    t.identifier('__pluginHostImports'),
                                    t.stringLiteral(importSource),
                                    true
                                )
                                return t.variableDeclarator(
                                    t.identifier(varName),
                                    sourceName === 'default'
                                        ? importExpression
                                        : t.memberExpression(importExpression, t.stringLiteral(sourceName), true)
                                )
                            })
                        )
                    )
                },
            },
            CallExpression: {
                exit(path: any) {
                    const { node } = path
                    if (t.isIdentifier(node.callee) && node.callee.name === 'require' && node.arguments.length === 1) {
                        const importSource = node.arguments[0].value

                        if (typeof imports[importSource] === 'undefined') {
                            throw new Error(
                                `Cannot import '${importSource}'! This package is not provided by PostHog in plugins.`
                            )
                        }

                        usedImports.add(importSource)

                        path.replaceWith(
                            t.memberExpression(t.identifier('__pluginHostImports'), t.stringLiteral(importSource), true)
                        )
                    }
                },
            },
        },
    })
