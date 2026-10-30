// Finds components that use a stylesheet's class without importing the stylesheet (see check-css-coupling.mjs).

// Only PascalCase block classes count, like `.PropertyFilters` or `.LemonButton`. Lower-case top-level
// classes in our stylesheets often share a name with a Tailwind utility (`.flex`, `.hidden`), and a match
// on those would flag every component that uses the utility.
const BLOCK_CLASS = /^[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*$/

function stripScssComments(source) {
    // A `//` after `(` or `:` is part of a value such as `url(//host/x.png)`, not a comment.
    return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[\s;{}])\/\/.*$/gm, '$1')
}

/** The block classes a stylesheet defines in its top-level selectors. */
export function rootClassesOf(scss) {
    const source = stripScssComments(scss)
    const classes = new Set()
    let depth = 0
    let prelude = ''
    for (let i = 0; i < source.length; i++) {
        const char = source[i]
        // `#{$var}` interpolation braces do not open a block.
        if (char === '#' && source[i + 1] === '{') {
            const close = source.indexOf('}', i)
            if (close === -1) {
                break
            }
            if (depth === 0) {
                prelude += source.slice(i, close + 1)
            }
            i = close
            continue
        }
        if (char === '{') {
            if (depth === 0) {
                for (const name of blockClassesInPrelude(prelude)) {
                    classes.add(name)
                }
            }
            depth++
            prelude = ''
        } else if (char === '}') {
            depth = Math.max(0, depth - 1)
            prelude = ''
        } else if (char === ';') {
            prelude = ''
        } else if (depth === 0) {
            prelude += char
        }
    }
    return [...classes].sort()
}

function blockClassesInPrelude(prelude) {
    const trimmed = prelude.trim()
    if (trimmed.startsWith('@')) {
        return []
    }
    const names = []
    for (const selector of trimmed.split(',')) {
        const name = /^\.([\w-]+)/.exec(selector.trim())?.[1]
        if (name && BLOCK_CLASS.test(name) && !name.includes('__') && !name.includes('--')) {
            names.push(name)
        }
    }
    return names
}

// Reads a quoted string that starts at `start`. Returns its text and the index of the closing quote.
function readQuoted(source, start) {
    const quote = source[start]
    let text = ''
    let i = start + 1
    while (i < source.length && source[i] !== quote) {
        if (source[i] === '\\') {
            i++
        }
        text += source[i]
        i++
    }
    return { text, end: i }
}

// A placeholder for a `${...}` hole, so `Foo${suffix}` does not read as the class `Foo`.
const HOLE = '\u0000'

// Collects the string literals of a JS expression in braces that starts at `start`.
function readExpressionStrings(source, start, strings) {
    let depth = 0
    for (let i = start; i < source.length; i++) {
        const char = source[i]
        if (char === '"' || char === "'") {
            const { text, end } = readQuoted(source, i)
            strings.push(text)
            i = end
        } else if (char === '`') {
            let text = ''
            i++
            while (i < source.length && source[i] !== '`') {
                if (source[i] === '\\') {
                    text += source[i + 1]
                    i += 2
                } else if (source[i] === '$' && source[i + 1] === '{') {
                    text += HOLE
                    i = readExpressionStrings(source, i + 1, strings) + 1
                } else {
                    text += source[i]
                    i++
                }
            }
            strings.push(text)
        } else if (char === '{') {
            depth++
        } else if (char === '}') {
            depth--
            if (depth === 0) {
                return i
            }
        }
    }
    return source.length
}

/** The class names a component passes in string literals to `className` and `*ClassName` props. */
export function classNamesUsedIn(tsx) {
    const strings = []
    for (const match of tsx.matchAll(/\b(?:className|\w+ClassName)\s*=\s*/g)) {
        const start = match.index + match[0].length
        const char = tsx[start]
        if (char === '"' || char === "'") {
            strings.push(readQuoted(tsx, start).text)
        } else if (char === '{') {
            readExpressionStrings(tsx, start, strings)
        }
    }
    const names = new Set()
    for (const text of strings) {
        for (const token of text.split(/\s+/)) {
            if (token && !token.includes(HOLE)) {
                names.add(token)
            }
        }
    }
    return names
}

/** True when `file` or anything it statically imports, directly or transitively, is one of `targets`. */
export function reachesAny(files, file, targets) {
    const seen = new Set([file])
    const queue = [file]
    while (queue.length) {
        const current = queue.shift()
        if (targets.has(current)) {
            return true
        }
        for (const next of files[current]?.staticImports ?? []) {
            if (!seen.has(next)) {
                seen.add(next)
                queue.push(next)
            }
        }
    }
    return false
}

const isSource = (file) => !file.includes('node_modules/')

/**
 * Every component that uses a block class but does not statically reach a stylesheet that defines it.
 * `files` is the import graph from importGraph.mjs, and `readSource` returns a file's text.
 */
export function findCouplings(files, readSource) {
    const sheetsByClass = new Map()
    for (const file of Object.keys(files)) {
        if (!isSource(file) || !/\.s?css$/.test(file)) {
            continue
        }
        for (const name of rootClassesOf(readSource(file))) {
            sheetsByClass.set(name, [...(sheetsByClass.get(name) ?? []), file])
        }
    }
    const couplings = []
    for (const file of Object.keys(files)) {
        if (!isSource(file) || !file.endsWith('.tsx')) {
            continue
        }
        for (const name of classNamesUsedIn(readSource(file))) {
            const sheets = sheetsByClass.get(name)
            if (sheets && !reachesAny(files, file, new Set(sheets))) {
                couplings.push({ file, className: name, stylesheets: sheets.sort() })
            }
        }
    }
    return couplings.sort((a, b) => a.file.localeCompare(b.file) || a.className.localeCompare(b.className))
}

/** The baseline line for a coupling. */
export const couplingKey = ({ file, className }) => `${file} -> .${className}`
