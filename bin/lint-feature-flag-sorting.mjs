#!/usr/bin/env node
/**
 * Linter to enforce alphabetical sorting of FEATURE_FLAGS in constants.tsx
 *
 * The FEATURE_FLAGS object is divided into sections by comment headers.
 * Within each section, flags must be sorted alphabetically by key name.
 *
 * Usage:
 *   node bin/lint-feature-flag-sorting.mjs [--fix]
 */

import { readFileSync, writeFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const CONSTANTS_PATH = resolve(__dirname, '../frontend/src/lib/constants.tsx')

const FIX_MODE = process.argv.includes('--fix')

function extractFeatureFlagsBlock(content) {
    const startMatch = content.match(/export const FEATURE_FLAGS = \{/)
    if (!startMatch) {
        throw new Error('Could not find FEATURE_FLAGS export in constants.tsx')
    }

    const startIndex = startMatch.index + startMatch[0].length
    let braceCount = 1
    let endIndex = startIndex

    while (braceCount > 0 && endIndex < content.length) {
        const char = content[endIndex]
        if (char === '{') {
            braceCount++
        } else if (char === '}') {
            braceCount--
        }
        endIndex++
    }

    return {
        before: content.slice(0, startMatch.index + startMatch[0].length),
        block: content.slice(startIndex, endIndex - 1),
        after: content.slice(endIndex - 1),
    }
}

function isSectionHeader(trimmed) {
    if (!trimmed.startsWith('//')) {
        return false
    }
    if (trimmed.includes('owner:') || trimmed.includes('see `')) {
        return false
    }
    const text = trimmed.slice(2).trim()
    if (text.length < 10) {
        return false
    }
    const lowerText = text.toLowerCase()
    return (
        lowerText.includes('flag') ||
        lowerText.includes('should') ||
        lowerText.includes('override') ||
        lowerText.includes('ux') ||
        lowerText.includes('wip') ||
        lowerText.includes('forever') ||
        lowerText.includes('legacy') ||
        lowerText.includes('temporary') ||
        lowerText.includes('control')
    )
}

function parseFlagEntries(block) {
    const lines = block.split('\n')
    const sections = []
    let currentSection = { headerLines: [], entries: [], name: null }

    let i = 0
    while (i < lines.length) {
        const line = lines[i]
        const trimmed = line.trim()

        if (trimmed === '') {
            i++
            continue
        }

        if (isSectionHeader(trimmed)) {
            if (currentSection.entries.length > 0 || currentSection.headerLines.length > 0) {
                sections.push(currentSection)
            }
            currentSection = { headerLines: [line], entries: [], name: trimmed.slice(2).trim() }
            i++
            continue
        }

        const flagMatch = line.match(/^\s*([A-Z][A-Z0-9_]*)\s*:\s*['"]([^'"]+)['"]/)
        if (flagMatch) {
            let precedingComment = null
            if (i > 0) {
                const prevLine = lines[i - 1]
                const prevTrimmed = prevLine.trim()
                if (prevTrimmed.endsWith('*/')) {
                    let commentStart = i - 1
                    while (commentStart > 0 && !lines[commentStart].trim().startsWith('/*')) {
                        commentStart--
                    }
                    if (lines[commentStart].trim().startsWith('/*')) {
                        precedingComment = lines.slice(commentStart, i).join('\n')
                    }
                }
            }

            currentSection.entries.push({
                key: flagMatch[1],
                line: line,
                precedingComment: precedingComment,
            })
            i++
            continue
        }

        if (trimmed.startsWith('/*') || trimmed.startsWith('*') || trimmed.endsWith('*/')) {
            i++
            continue
        }

        i++
    }

    if (currentSection.entries.length > 0 || currentSection.headerLines.length > 0) {
        sections.push(currentSection)
    }

    return { sections }
}

function checkSorting(sections) {
    const errors = []

    for (const section of sections) {
        if (section.entries.length < 2) {
            continue
        }

        const keys = section.entries.map((e) => e.key)
        const sortedKeys = [...keys].sort((a, b) => a.localeCompare(b))

        for (let i = 0; i < keys.length; i++) {
            if (keys[i] !== sortedKeys[i]) {
                const outOfPlace = keys.filter((key, idx) => key !== sortedKeys[idx])
                errors.push({
                    section: section.name || 'unnamed section',
                    message: `Keys are not alphabetically sorted. Out of order: ${outOfPlace.slice(0, 3).join(', ')}${outOfPlace.length > 3 ? '...' : ''}`,
                    expected: sortedKeys,
                    actual: keys,
                })
                break
            }
        }
    }

    return errors
}

function sortSection(section) {
    if (section.entries.length < 2) {
        return section
    }

    const sortedEntries = [...section.entries].sort((a, b) => a.key.localeCompare(b.key))
    return { ...section, entries: sortedEntries }
}

function reconstructBlock(sections) {
    const parts = []

    for (let s = 0; s < sections.length; s++) {
        const section = sections[s]

        if (s > 0) {
            parts.push('')
        }

        for (const headerLine of section.headerLines) {
            parts.push(headerLine)
        }

        for (const entry of section.entries) {
            if (entry.precedingComment) {
                parts.push(entry.precedingComment)
            }
            parts.push(entry.line)
        }
    }

    return '\n' + parts.join('\n') + '\n    '
}

function main() {
    let content
    try {
        content = readFileSync(CONSTANTS_PATH, 'utf-8')
    } catch (err) {
        console.error(`Error reading ${CONSTANTS_PATH}:`, err.message)
        process.exit(1)
    }

    const { before, block, after } = extractFeatureFlagsBlock(content)
    const { sections } = parseFlagEntries(block)
    const errors = checkSorting(sections)

    if (errors.length === 0) {
        console.info('✓ FEATURE_FLAGS are alphabetically sorted within each section')
        process.exit(0)
    }

    console.error('✗ FEATURE_FLAGS sorting errors found:\n')
    for (const error of errors) {
        console.error(`  Section: "${error.section}"`)
        console.error(`  ${error.message}\n`)
    }

    if (FIX_MODE) {
        const sortedSections = sections.map(sortSection)
        const newBlock = reconstructBlock(sortedSections)
        const newContent = before + newBlock + after

        writeFileSync(CONSTANTS_PATH, newContent)
        console.info('\n✓ FEATURE_FLAGS have been sorted. Please review the changes.')
        process.exit(0)
    } else {
        console.error('Run with --fix to automatically sort the flags.')
        process.exit(1)
    }
}

main()
