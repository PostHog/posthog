import {
    htmlSanitizationWouldStrip,
    sanitizeExperimentHTML,
    sanitizeExperimentStyle,
    setSanitizedHTML,
    setSanitizedStyle,
    styleSanitizationWouldStrip,
} from './sanitize'

describe('experiment sanitize', () => {
    describe('sanitizeExperimentHTML', () => {
        it.each([
            ['empty', '', ''],
            ['plain text passes through', 'Hello world', 'Hello world'],
            ['basic markup passes through', '<p><strong>Hi</strong></p>', '<p><strong>Hi</strong></p>'],
            [
                'anchor with href passes through',
                '<a href="https://example.com">x</a>',
                '<a href="https://example.com">x</a>',
            ],
        ])('%s', (_name, input, expected) => {
            expect(sanitizeExperimentHTML(input)).toBe(expected)
        })

        it.each([
            ['script tag', '<script>alert(1)</script>'],
            ['img onerror handler', '<img src=x onerror="alert(1)">'],
            ['svg onload handler', '<svg onload="alert(1)"></svg>'],
            ['anchor with javascript: href', '<a href="javascript:alert(1)">x</a>'],
            ['iframe srcdoc', '<iframe srcdoc="<script>alert(1)</script>"></iframe>'],
            ['form with formaction', '<form action="https://evil/"></form>'],
            ['object data URL', '<object data="data:text/html,<script>alert(1)</script>"></object>'],
            ['embed', '<embed src="https://evil/">'],
            ['link rel', '<link rel="stylesheet" href="https://evil/">'],
            ['inline style tag with url()', '<style>body{background:url(https://evil/)}</style>'],
            ['style attribute with url()', '<div style="background:url(https://evil/)">x</div>'],
            ['style attribute legitimate', '<div style="color:red">x</div>'],
        ])('strips dangerous content: %s', (_name, input) => {
            const out = sanitizeExperimentHTML(input)
            expect(out).not.toMatch(/javascript:/i)
            expect(out).not.toMatch(/onerror=/i)
            expect(out).not.toMatch(/onload=/i)
            expect(out).not.toMatch(/<script/i)
            expect(out).not.toMatch(/<iframe/i)
            expect(out).not.toMatch(/<style/i)
            expect(out).not.toMatch(/<object/i)
            expect(out).not.toMatch(/<embed/i)
            expect(out).not.toMatch(/<link/i)
            expect(out).not.toMatch(/style=/i)
            expect(out).not.toMatch(/srcdoc=/i)
            expect(out).not.toMatch(/formaction=/i)
        })
    })

    describe('sanitizeExperimentStyle', () => {
        it('drops url() declarations', () => {
            const out = sanitizeExperimentStyle('color: red; background-image: url(https://evil/leak)')
            expect(out).toMatch(/color:\s*red/i)
            expect(out).not.toMatch(/url\(/i)
        })

        it.each([
            'background-image: image-set(url(https://evil/) 1x)',
            'background: -webkit-image-set(url(https://evil/) 1x)',
            'background: cross-fade(url(a) 50%, url(b) 50%)',
            'background: paint(myPainter)',
            'background-image: expression(alert(1))',
            // CSS character escapes: `\l` is a literal `l`, so the parser resolves to url().
            'background-image: ur\\l(https://evil/)',
            'background-image: u\\72l(https://evil/)',
        ])('drops fetching-function declaration: %s', (input) => {
            const out = sanitizeExperimentStyle(input)
            expect(out).not.toMatch(/url\(/i)
            expect(out).not.toMatch(/image-set\(/i)
            expect(out).not.toMatch(/cross-fade\(/i)
            expect(out).not.toMatch(/paint\(/i)
            expect(out).not.toMatch(/expression\(/i)
        })

        it.each([
            'color: red',
            'font-weight: bold',
            'padding: 10px 20px',
            'border: 1px solid #ccc',
            'text-decoration: underline',
            'transform: translateX(10px)',
        ])('preserves safe declaration: %s', (input) => {
            const out = sanitizeExperimentStyle(input)
            expect(out.length).toBeGreaterThan(0)
        })

        it.each([
            ['null', null],
            ['undefined', undefined],
            ['empty', ''],
        ])('returns empty for %s', (_name, input) => {
            expect(sanitizeExperimentStyle(input as any)).toBe('')
        })
    })

    describe('setSanitizedHTML', () => {
        it('writes sanitized markup to innerHTML', () => {
            const el = document.createElement('div')
            // nosemgrep: javascript.lang.security.audit.unknown-value-with-script-tag.unknown-value-with-script-tag
            setSanitizedHTML(el, '<p>hi<script>alert(1)</script></p>')
            expect(el.innerHTML).toBe('<p>hi</p>')
        })
    })

    describe('setSanitizedStyle', () => {
        it('writes a sanitized style attribute when content survives', () => {
            const el = document.createElement('div')
            setSanitizedStyle(el, 'color: blue; background: url(https://evil/)')
            const style = el.getAttribute('style') || ''
            expect(style).toMatch(/blue/)
            expect(style).not.toMatch(/url\(/)
        })

        it('removes the style attribute entirely when nothing survives', () => {
            const el = document.createElement('div')
            el.setAttribute('style', 'color: red')
            setSanitizedStyle(el, '')
            expect(el.hasAttribute('style')).toBe(false)
        })

        it('removes the style attribute when input is undefined', () => {
            const el = document.createElement('div')
            setSanitizedStyle(el, undefined)
            expect(el.hasAttribute('style')).toBe(false)
        })
    })

    describe('htmlSanitizationWouldStrip', () => {
        it.each([
            ['null', null, false],
            ['empty', '', false],
            ['plain text', 'hi', false],
            ['safe markup', '<p>hi</p>', false],
            ['onerror handler', '<img src=x onerror=alert(1)>', true],
            ['script tag', '<script>x</script>', true],
            ['style attribute', '<div style="color:red">x</div>', true],
        ])('%s -> %s', (_name, input, expected) => {
            expect(htmlSanitizationWouldStrip(input as any)).toBe(expected)
        })
    })

    describe('styleSanitizationWouldStrip', () => {
        it.each([
            ['null', null, false],
            ['empty', '', false],
            ['safe declaration', 'color: red', false],
            ['safe multi-declaration', 'color: red; padding: 10px', false],
            ['url()', 'background-image: url(https://evil/)', true],
            ['mixed safe + unsafe', 'color: red; background: url(https://evil/)', true],
        ])('%s -> %s', (_name, input, expected) => {
            expect(styleSanitizationWouldStrip(input as any)).toBe(expected)
        })
    })
})
