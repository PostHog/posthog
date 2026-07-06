import { describe, expect, it } from 'vitest'

import { markdownToMrkdwn } from './slack-mrkdwn'

describe('markdownToMrkdwn', () => {
    describe('emphasis', () => {
        it.each([
            ['**bold**', '*bold*'],
            ['__bold__', '*bold*'],
            ['*italic*', '_italic_'],
            ['_italic_', '_italic_'],
            ['***bolditalic***', '*_bolditalic_*'],
            ['**a** **b**', '*a* *b*'],
            ['**a** and *b*', '*a* and _b_'],
            ['plain **bold** plain *italic* plain', 'plain *bold* plain _italic_ plain'],
            ['**bold _em_ inside**', '*bold _em_ inside*'],
            ['**a *b* c**', '*a _b_ c*'],
            ['**Status:** open', '*Status:* open'],
            ['ends with **bold**', 'ends with *bold*'],
            ['~~struck~~', '~struck~'],
            ['~~a~~ and ~~b~~', '~a~ and ~b~'],
            ['already ~strike~', 'already ~strike~'],
        ])('%j -> %j', (input, expected) => {
            expect(markdownToMrkdwn(input)).toBe(expected)
        })
    })

    describe('headings', () => {
        it.each([
            ['# H1', '*H1*'],
            ['## H2', '*H2*'],
            ['###### H6', '*H6*'],
            ['#  extra spaces  ', '*extra spaces*'],
            ['## With **bold** in it', '*With bold in it*'],
            ['## See [docs](https://x.io)', '*See <https://x.io|docs>*'],
            ['#nospace', '#nospace'],
            ['text # not a heading', 'text # not a heading'],
        ])('%j -> %j', (input, expected) => {
            expect(markdownToMrkdwn(input)).toBe(expected)
        })
    })

    describe('lists and tasks', () => {
        it.each([
            ['- a', '• a'],
            ['* a', '• a'],
            ['+ a', '• a'],
            ['- **bold** item', '• *bold* item'],
            ['  - nested', '  • nested'],
            ['1. first', '1. first'],
            ['1. **bold**', '1. *bold*'],
            ['10. tenth', '10. tenth'],
            ['- [ ] todo', '• ☐ todo'],
            ['- [x] done', '• ☑ done'],
            ['- [X] done caps', '• ☑ done caps'],
            ['-nospace', '-nospace'],
            ['a - b', 'a - b'],
        ])('%j -> %j', (input, expected) => {
            expect(markdownToMrkdwn(input)).toBe(expected)
        })

        it('a multi-line list', () => {
            expect(markdownToMrkdwn('- one\n* two\n+ three')).toBe('• one\n• two\n• three')
        })
    })

    describe('links and images', () => {
        it.each([
            ['[t](https://x.io)', '<https://x.io|t>'],
            ['[t](https://x.io "title")', '<https://x.io|t>'],
            ['[t](https://x.io?a=1&b=2)', '<https://x.io?a=1&b=2|t>'],
            ['![alt](https://img.png)', '<https://img.png>'],
            ['![](https://img.png)', '<https://img.png>'],
            ['![a](i.png) then [b](l.io)', '<i.png> then <l.io|b>'],
            ['[**bold link**](https://x.io)', '<https://x.io|*bold link*>'],
            ['**[t](https://x.io)**', '*<https://x.io|t>*'],
            ['bare https://x.io stays', 'bare https://x.io stays'],
        ])('%j -> %j', (input, expected) => {
            expect(markdownToMrkdwn(input)).toBe(expected)
        })
    })

    describe('code is shielded', () => {
        it.each([
            ['use `code` here', 'use `code` here'],
            ['`**not bold**`', '`**not bold**`'],
            ['`# not heading`', '`# not heading`'],
            ['`a` and `b`', '`a` and `b`'],
        ])('%j -> %j', (input, expected) => {
            expect(markdownToMrkdwn(input)).toBe(expected)
        })

        it('leaves fenced blocks (and their markdown) untouched', () => {
            expect(markdownToMrkdwn('```\n**x**\n- y\n# z\n```')).toBe('```\n**x**\n- y\n# z\n```')
        })

        it('leaves a language-tagged fence untouched', () => {
            expect(markdownToMrkdwn('```ts\nconst a = `**x**`\n```')).toBe('```ts\nconst a = `**x**`\n```')
        })

        it('converts around a fenced block but not inside', () => {
            expect(markdownToMrkdwn('**before**\n```\n**inside**\n```\n**after**')).toBe(
                '*before*\n```\n**inside**\n```\n*after*'
            )
        })
    })

    describe('blockquotes and rules', () => {
        it.each([
            ['> quote', '> quote'],
            ['> **important**', '> *important*'],
            ['---', '──────────'],
            ['***', '──────────'],
            ['___', '──────────'],
            ['----', '──────────'],
        ])('%j -> %j', (input, expected) => {
            expect(markdownToMrkdwn(input)).toBe(expected)
        })
    })

    describe('no false positives on literal punctuation', () => {
        it.each([
            ['snake_case_var', 'snake_case_var'],
            ['a_b_c_d', 'a_b_c_d'],
            ['2 * 3 = 6', '2 * 3 = 6'],
            ['plain text', 'plain text'],
            ['', ''],
            ['   ', '   '],
            ['emoji 🎉 and :smile:', 'emoji 🎉 and :smile:'],
            ['**unclosed', '**unclosed'],
            ['a > b comparison', 'a > b comparison'],
        ])('%j -> %j', (input, expected) => {
            expect(markdownToMrkdwn(input)).toBe(expected)
        })
    })

    describe('realistic mixed messages', () => {
        it('a kudos-bot style digest', () => {
            const md = [
                '# Kudos — week of Jun 16',
                '',
                '- **Alice** → **Bob**: shipped the _migration_ early',
                '- **Carol** → **Dan**: caught a [regression](https://gh.io/pr/1)',
                '',
                '---',
                '',
                'See `pinned-kudos.md` for the full list.',
            ].join('\n')
            const out = markdownToMrkdwn(md)
            expect(out).toContain('*Kudos — week of Jun 16*')
            expect(out).toContain('• *Alice* → *Bob*: shipped the _migration_ early')
            expect(out).toContain('caught a <https://gh.io/pr/1|regression>')
            expect(out).toContain('──────────')
            expect(out).toContain('`pinned-kudos.md`')
            expect(out).not.toContain('**')
        })

        it('an idea card like the screenshot', () => {
            const md =
                '**Self-Building Documentation Bot** (`self-building-documentation-bot`)\n\n' +
                '> A documentation bot that installs anywhere.\n\n' +
                '- **Status:** open\n- **Feasibility:** High\n\n---\n\nGot more ideas? 👀'
            const out = markdownToMrkdwn(md)
            expect(out).toContain('*Self-Building Documentation Bot* (`self-building-documentation-bot`)')
            expect(out).toContain('> A documentation bot that installs anywhere.')
            expect(out).toContain('• *Status:* open')
            expect(out).toContain('──────────')
            expect(out).not.toContain('**')
            expect(out).not.toContain('---')
        })
    })

    // Documented limitations — Slack has no equivalent / a real parser would be
    // needed. Asserted so the behaviour is pinned, not silently "correct".
    describe('known limitations', () => {
        it.each([
            ['bare * pairs read as italic: 2 * 3 * 4', 'math', '2 _ 3 _ 4'],
            ['spaced rule not detected: - - -', 'rule', '• - -'],
            ['tilde fence not a code block: ~~~', 'fence', '~~~'],
        ])('%s (%s)', (input, _kind, expected) => {
            const text = input.slice(input.indexOf(': ') + 2)
            expect(markdownToMrkdwn(text)).toBe(expected)
        })
    })
})
