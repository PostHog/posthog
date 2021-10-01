// inspired by: https://github.com/treywood/babel-plugin-bluebird-async-functions/

import { PluginGen } from './common'

const REPLACED = Symbol()

export const promiseTimeout: PluginGen =
    () =>
    ({ types: t }) => ({
        visitor: {
            // Turn `bla.then` into `asyncGuard(bla).then`
            MemberExpression: {
                exit(path: any) {
                    const { node } = path
                    if (
                        node?.property &&
                        t.isIdentifier(node.property) &&
                        node.property.name === 'then' &&
                        !node[REPLACED]
                    ) {
                        const newCall = t.memberExpression(
                            t.callExpression(t.identifier('__asyncGuard'), [node.object]),
                            t.identifier('then')
                        )
                        ;(newCall as any)[REPLACED] = true
                        path.replaceWith(newCall)
                    }
                },
            },

            // Turn `await bla` into `await __asyncGuard(bla)`
            AwaitExpression: {
                exit(path: any) {
                    const { node } = path
                    if (node && !node[REPLACED]) {
                        const newAwait = t.awaitExpression(
                            t.callExpression(t.identifier('__asyncGuard'), [
                                node.argument,
                                node.argument.callee || node.argument,
                            ])
                        )
                        ;(newAwait as any)[REPLACED] = true
                        path.replaceWith(newAwait)
                    }
                },
            },
        },
    })
