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
            '<a href="https://example.com">https://example.com</a> or <a href="mailto:help@example.com">help@example.com</a>',
            'https://example.com or help@example.com',
        ],
        [
            'an image-only link',
            '<a href="https://example.com/app"><img src="logo.png" alt="Logo"></a>',
            'https://example.com/app',
        ],
        ['a page anchor link', '<a href="#top">Back to top</a>', 'Back to top'],
        [
            'entities',
            '<p>Tom&nbsp;&amp;&nbsp;Jerry&#8217;s &#x1F600; &copy; R&eacute;initialiser &laquo;ok&raquo;</p>',
            'Tom & Jerry’s 😀 © Réinitialiser «ok»',
        ],
        [
            'a greater-than sign inside an attribute value',
            '<a title="1 > 0" href="https://example.com/?q=a>b">Open</a>',
            'Open (https://example.com/?q=a>b)',
        ],
        [
            'a hidden preheader with padding',
            '<body><div style="display: none; max-height: 0">Preview<div>nested</div> &zwnj;&#8204;&#847;</div>Hello</body>',
            'Hello',
        ],
        ['a hidden void element', '<img src="pixel.gif" style="display:none"><p>Hello</p>', 'Hello'],
        [
            'comments and conditional comments',
            '<!--[if mso]><table><tr><td>Outlook only</td></tr></table><![endif]--><p>Hi</p><!-- unterminated',
            'Hi',
        ],
        ['a literal less-than sign', '<p>1 < 2 and 3 > 2</p>', '1 < 2 and 3 > 2'],
        ['lists and line breaks', '<ul><li>One</li><li>Two</li></ul>Line<br>Next', '- One\n- Two\n\nLine\nNext'],
        ['table cells', '<table><tr><td>Total</td><td>$5</td></tr></table>', 'Total $5'],
    ])('renders %s', (_case, html, expected) => {
        expect(plainTextFromHtml(html)).toBe(expected)
    })
})
