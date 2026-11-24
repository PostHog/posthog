import { plainTextFromHtml } from './email-text'

describe('plainTextFromHtml', () => {
    it.each([
        [
            'a login code email',
            `<!DOCTYPE html><html><head><title>Sign in</title><style>p { color: red; }</style></head>
             <body><h1>Your code</h1><p>Use   this code
             to sign in:</p><p><strong>482913</strong></p><script>track()</script></body></html>`,
            'Your code\n\nUse this code to sign in:\n\n482913',
        ],
        [
            'links with their targets',
            '<p><a href="https://example.com/reset?a=1&amp;b=2">Reset password</a></p>',
            'Reset password (https://example.com/reset?a=1&b=2)',
        ],
        [
            'a link whose label is its target',
            '<a href="https://example.com">https://example.com</a>',
            'https://example.com',
        ],
        [
            'an image link without alt text',
            '<a href="https://example.com/app"><img src="logo.png"></a>',
            'https://example.com/app',
        ],
        [
            'hidden preheaders in the spellings email builders write',
            '<div style="display: none; max-height: 0">Preview &zwnj;</div>' +
                '<div style="DISPLAY:NONE !important">Old</div><p>Hello</p>',
            'Hello',
        ],
        ['an element with the hidden attribute', '<div hidden>Preview</div><p>Hello</p>', 'Hello'],
        [
            'styled elements that stay visible',
            '<p style="margin:0">Reset</p><a style="color:red" href="https://example.com/r">here</a>',
            'Reset\n\nhere (https://example.com/r)',
        ],
        ['table cells', '<table><tr><td>Total</td><td>$5</td></tr></table>', 'Total\n$5'],
        ['a list', '<p>Steps</p><ul><li>Open</li><li>Copy</li></ul>', 'Steps\n\n * Open\n * Copy'],
        ['an image-only email', '<p><img src="banner.png" alt="Sale"></p>', ''],
        ['html longer than the converter reads', '<p>Hi</p>' + ' '.repeat(1 << 18), ''],
        ['html nested deeper than the stack allows', '<div>'.repeat(20000) + 'Hi' + '</div>'.repeat(20000), ''],
        ['markup that renders longer than its html', '<p>Hi</p>' + '<hr>'.repeat(1000), ''],
    ])('renders %s', (_name, html, expected) => {
        expect(plainTextFromHtml(html)).toBe(expected)
    })
})
