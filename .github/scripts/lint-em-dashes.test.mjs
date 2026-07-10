import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fixLine, parseAddedLineNumbers } from './lint-em-dashes.mjs'

test('fixLine replaces em dashes with a spaced hyphen', () => {
    const cases = [
        ['a—b', 'a - b'], // unspaced
        ['a — b', 'a - b'], // already spaced
        ['a―b', 'a - b'], // horizontal bar U+2015
        ['    # note — really', '    # note - really'], // leading indent preserved
        ['— leading', '- leading'], // dash at start gains no leading space
        ['trailing—', 'trailing -'], // dash at end leaves no trailing space
        ['a——b', 'a - b'], // consecutive dashes collapse
        ['multi—dash—line', 'multi - dash - line'],
        ['no dash here', 'no dash here'], // untouched
        ['', ''],
    ]
    for (const [input, expected] of cases) {
        assert.equal(fixLine(input), expected, `fixLine(${JSON.stringify(input)})`)
    }
})

test('parseAddedLineNumbers reads new-side lines from hunk headers', () => {
    // Single-line hunk with no count -> one line.
    assert.deepEqual([...parseAddedLineNumbers('@@ -1 +5 @@ ctx')], [5])

    // Multi-line hunk -> the whole range.
    assert.deepEqual([...parseAddedLineNumbers('@@ -1,0 +2,3 @@')], [2, 3, 4])

    // Pure deletion (`+c,0`) adds nothing.
    assert.deepEqual([...parseAddedLineNumbers('@@ -3,2 +2,0 @@')], [])

    // Multiple hunks accumulate.
    const diff = ['@@ -1 +1 @@', 'context', '@@ -10,0 +11,2 @@', '+a', '+b'].join('\n')
    assert.deepEqual([...parseAddedLineNumbers(diff)].sort((a, b) => a - b), [1, 11, 12])

    // A new file reports every added line.
    assert.deepEqual([...parseAddedLineNumbers('@@ -0,0 +1,4 @@')], [1, 2, 3, 4])

    // No hunk headers -> nothing.
    assert.equal(parseAddedLineNumbers('diff --git a/x b/x\n+content').size, 0)
})
