import type { ASTNode, ParseResult } from '@posthog/hogql-parser'

import { parseProgram } from 'scenes/data-warehouse/editor/hogqlParserSingleton'

function isConstantTrue(node: ASTNode | null | undefined): boolean {
    return node?.node === 'Constant' && node.value === true
}

// Hog has no `break`, so a loop whose condition can never be false only exits through a return or throw.
function isEndlessLoop(node: ASTNode): boolean {
    if (node.node === 'WhileStatement') {
        return isConstantTrue(node.expr)
    }
    return node.node === 'ForStatement' && (node.condition == null || isConstantTrue(node.condition))
}

function alwaysExits(node: ASTNode | null | undefined): boolean {
    if (!node) {
        return false
    }
    switch (node.node) {
        case 'ReturnStatement':
        case 'ThrowStatement':
            return true
        case 'Block':
            return node.declarations.some(alwaysExits)
        case 'IfStatement':
            if (isConstantTrue(node.expr)) {
                return alwaysExits(node.then)
            }
            return alwaysExits(node.then) && alwaysExits(node.else_)
        case 'TryCatchStatement': {
            const catchBlocks: ASTNode[] = node.catches.map(([, , block]: [string, string | null, ASTNode]) => block)
            return (alwaysExits(node.try_stmt) && catchBlocks.every(alwaysExits)) || alwaysExits(node.finally_stmt)
        }
        case 'WhileStatement':
        case 'ForStatement':
            return isEndlessLoop(node)
        default:
            return false
    }
}

// A transformation that reaches the end of its code returns null, so the event is dropped.
export async function canFinishWithoutReturn(code: string): Promise<boolean> {
    let program: ParseResult
    try {
        program = JSON.parse(await parseProgram(code, true))
    } catch {
        return false
    }
    if ('error' in program || program.node !== 'Program' || program.declarations.length === 0) {
        return false
    }
    return !program.declarations.some(alwaysExits)
}
