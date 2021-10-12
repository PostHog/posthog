// Inspiration:
// https://medium.com/@bvjebin/js-infinite-loops-killing-em-e1c2f5f2db7f
// https://github.com/jsbin/loop-protect/blob/master/lib/index.js

import * as types from '@babel/types'

import { PluginGen } from './common'

const generateBefore = (t: typeof types, id: any) =>
    t.variableDeclaration('const', [
        t.variableDeclarator(id, t.callExpression(t.memberExpression(t.identifier('Date'), t.identifier('now')), [])),
    ])

const generateInside = ({
    t,
    id,
    line,
    ch,
    timeout,
}: {
    t: typeof types
    id: types.Identifier
    line: number
    ch: number
    timeout: number
}) => {
    return t.ifStatement(
        t.binaryExpression(
            '>',
            t.binaryExpression(
                '-',
                t.callExpression(t.memberExpression(t.identifier('Date'), t.identifier('now')), []),
                id
            ),
            t.numericLiteral(timeout * 1000)
        ),
        t.throwStatement(
            t.newExpression(t.identifier('Error'), [
                t.stringLiteral(
                    `Script execution timed out after looping for ${timeout} second${
                        timeout === 1 ? '' : 's'
                    } on line ${line}:${ch}`
                ),
            ])
        )
    )
}

const protect =
    (t: typeof types, timeout: number) =>
    (path: any): void => {
        if (!path.node.loc) {
            // I don't really know _how_ we get into this state, but https://jsbin.com/mipesawapi/1/ triggers it,
            // and the node, I'm guessing after translation, doesn't have a line in the code, so this blows up.
            return
        }
        const id = path.scope.generateUidIdentifier('LP')
        const before = generateBefore(t, id)
        const inside = generateInside({
            t,
            id,
            line: path.node.loc.start.line,
            ch: path.node.loc.start.column,
            timeout,
        })
        const body = path.get('body')

        // if we have an expression statement, convert it to a block
        if (!t.isBlockStatement(body)) {
            body.replaceWith(t.blockStatement([body.node]))
        }
        path.insertBefore(before)
        body.unshiftContainer('body', inside)
    }

export const loopTimeout: PluginGen =
    (server) =>
    ({ types: t }) => ({
        visitor: {
            WhileStatement: protect(t, server.TASK_TIMEOUT),
            ForStatement: protect(t, server.TASK_TIMEOUT),
            DoWhileStatement: protect(t, server.TASK_TIMEOUT),
        },
    })
