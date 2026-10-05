const FLAG_KEY = /^[a-z0-9][a-z0-9_-]{0,99}$/
const MAX_FLAGS = 20
const CONSTANTS_PATH = 'frontend/src/lib/constants.tsx'

function addedLines(patch) {
    return (patch || '')
        .split('\n')
        .filter((line) => line.startsWith('+') && !line.startsWith('+++'))
        .map((line) => line.slice(1))
}

function parseFlagConstants(source) {
    const block = /export const FEATURE_FLAGS = \{([\s\S]*?)\n\}/.exec(source || '')
    const constants = {}
    if (!block) {
        return constants
    }
    for (const match of block[1].matchAll(/^\s*([A-Z0-9_]+):\s*['"]([^'"]+)['"]/gm)) {
        constants[match[1]] = match[2]
    }
    return constants
}

function parseBodyFlags(body) {
    const match = /^\s*preview flags:\s*(.*)$/im.exec(body || '')
    if (!match) {
        return { disabled: false, keys: [] }
    }
    const value = match[1].trim()
    if (/^none$/i.test(value)) {
        return { disabled: true, keys: [] }
    }
    return {
        disabled: false,
        keys: value
            .split(/[\s,]+/)
            .map((key) => key.replace(/^`|`$/g, ''))
            .filter(Boolean),
    }
}

function scanFiles(files, constants) {
    const keys = []
    for (const file of files) {
        for (const line of addedLines(file.patch)) {
            if (file.filename === CONSTANTS_PATH) {
                const entry = /^\s*[A-Z0-9_]+:\s*['"]([^'"]+)['"]/.exec(line)
                if (entry) {
                    keys.push(entry[1])
                }
            }
            for (const ref of line.matchAll(/FEATURE_FLAGS\.([A-Z0-9_]+)/g)) {
                if (constants[ref[1]]) {
                    keys.push(constants[ref[1]])
                }
            }
            for (const call of line.matchAll(/feature_enabled\(\s*['"]([^'"]+)['"]/g)) {
                keys.push(call[1])
            }
        }
    }
    return keys
}

function detectPreviewFlags({ body, files, constantsSource }) {
    const fromBody = parseBodyFlags(body)
    const scanned = fromBody.disabled ? [] : scanFiles(files, parseFlagConstants(constantsSource))
    const unique = [...new Set([...fromBody.keys, ...scanned])].filter((key) => FLAG_KEY.test(key))
    return unique.slice(0, MAX_FLAGS)
}

module.exports = { CONSTANTS_PATH, detectPreviewFlags, parseBodyFlags, parseFlagConstants }
