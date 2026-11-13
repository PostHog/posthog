export function formatCompositeExpression(expression: string): string {
    let depth = 0
    let cursor = 0
    let formatted = ''

    for (const token of expression.matchAll(
        /"(?:\\.|[^"\\])*(?:"|$)|'(?:\\.|[^'\\])*(?:'|$)|\b(?:and|or|if|else)\b|[()[\]]/g
    )) {
        formatted += expression.slice(cursor, token.index)
        const value = token[0]
        if (['and', 'or', 'if', 'else'].includes(value)) {
            formatted = `${formatted.trimEnd()}\n${'  '.repeat(Math.max(0, depth - 1))}${value}`
        } else {
            formatted += value
            if (value === '(' || value === '[') {
                depth++
            } else if (value === ')' || value === ']') {
                depth = Math.max(0, depth - 1)
            }
        }
        cursor = token.index + value.length
    }

    return (formatted + expression.slice(cursor)).trim()
}
