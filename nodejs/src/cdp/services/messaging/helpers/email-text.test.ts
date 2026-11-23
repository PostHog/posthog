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
            'a URL label shorter than its target',
            '<a href="https://example.com/reset?t=1&amp;utm_source=posthog">https://example.com/reset</a>',
            'https://example.com/reset (https://example.com/reset?t=1&utm_source=posthog)',
        ],
        [
            'an image link with alt text',
            '<a href="https://example.com/app"><img src="logo.png" alt="Logo"></a>',
            'Logo (https://example.com/app)',
        ],
        [
            'an image link without alt text',
            '<a href="https://example.com/app"><img src="logo.png"></a>',
            'https://example.com/app',
        ],
        ['a javascript link', '<a href=" JavaScript:void(0)">Click</a>', 'Click'],
        ['a hidden javascript link', '<a style="display:none" href="javascript:void(0)">Hidden</a><p>Hi</p>', 'Hi'],
        ['a page anchor link', '<a href="#top">Back to top</a>', 'Back to top'],
        [
            'entities',
            '<p>Tom&nbsp;&amp;&nbsp;Jerry&#8217;s &#x1F600; &copy; R&eacute;initialiser &laquo;ok&raquo;</p>',
            'Tom\u00a0&\u00a0Jerry’s 😀 © Réinitialiser «ok»',
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
        ['a hidden void element', '<img src="pixel.gif" alt="pixel" style="DISPLAY:NONE"><p>Hello</p>', 'Hello'],
        ['an element with the hidden attribute', '<div hidden>Preview</div><p>Hello</p>', 'Hello'],
        [
            'hidden styles with any spacing or encoding',
            '<div title="1 > 0" style="display : none">Old code 123456</div><div style="display:&#32;none">Old</div>' +
                '<div style=\'font-family:"Arial"; DISPLAY:\tNONE !important\'>Older</div><p>Current code 482913</p>',
            'Current code 482913',
        ],
        [
            'styled elements that stay visible',
            '<p style="margin:0;text-decoration:none">Reset</p><a style="color:red" href="https://example.com/r">here</a>',
            'Reset\n\nhere (https://example.com/r)',
        ],
        ['style text shown as text', '<pre>Use style="display: none"</pre>', 'Use style="display: none"'],
        [
            'a link token with a soft hyphen',
            '<a href="https://example.com/reset?token=ab&#xAD;cd">Reset</a>',
            'Reset (https://example.com/reset?token=ab%C2%ADcd)',
        ],
        [
            'neighbouring center blocks',
            '<center>482913</center><center>10 minutes remaining</center>',
            '482913\n10 minutes remaining',
        ],
        [
            'content after the body',
            '<body><p>Sign in</p></body><p>Your code: 482913</p>',
            'Sign in\n\nYour code: 482913',
        ],
        ['html longer than the converter reads', '<p>Hi</p>' + ' '.repeat(1 << 20), ''],
        ['nested lists', '<ul><li>One<ul><li>Two</li></ul></li><li>Three</li></ul>', '- One\n- Two\n\n- Three'],
        ['lists nested many levels deep', '<ul><li>'.repeat(200) + 'Hi' + '</li></ul>'.repeat(200), '- Hi'],
        ['a list item that starts with a paragraph', '<ul><li><p>Step one</p></li></ul>', '-\n\nStep one'],
        [
            'a list item with text after its first paragraph',
            '<ul><li><p>Use 482913</p>Expires in 10 minutes</li></ul>',
            '-\n\nUse 482913\n\nExpires in 10 minutes',
        ],
        [
            'a list item that starts with a hidden preheader',
            '<ul><li><div style="display:none">Preview</div>Code 482913</li></ul>',
            '- Code 482913',
        ],
        [
            'a list item that holds only a linked image',
            '<ul><li><a href="https://example.com/reset"><img src="button.png"></a></li></ul>',
            '- https://example.com/reset',
        ],
        [
            'an ordered list with Roman numerals',
            '<p>Code: 1</p><ol type="I" start="4000"><li>Open</li></ol>',
            'Code: 1\n\n- Open',
        ],
        ['a code ending in a full stop', '<p>482913.</p>', '482913.'],
        ['a code split by a zero-width space', '<p>482&#8203;913</p>', '482913'],
        ['a code split by a soft hyphen', '<p>482&shy;913</p>', '482913'],
        ['a hyphen on a line of its own', '<pre>a\n-\nb</pre>', 'a\n-\nb'],
        ['an image-only ordered list', '<ol><li><img src="banner.png"></li></ol>', ''],
        ['a link with spaces around a page anchor', '<a href=" #top ">Back</a>', 'Back'],
        ['a code shown as an image', '<p>Your code:</p><img src="code.png" alt="482913">', 'Your code:\n\n482913'],
        [
            'comments and conditional comments',
            '<!--[if mso]><table><tr><td>Outlook only</td></tr></table><![endif]--><p>Hi</p><!-- unterminated',
            'Hi',
        ],
        ['a literal less-than sign', '<p>1 < 2 and 3 > 2</p>', '1 < 2 and 3 > 2'],
        ['nested quotes', '<blockquote><blockquote><p>Quoted</p></blockquote></blockquote>', 'Quoted'],
        ['punctuation only', '<p>??!</p>', '??!'],
        ['a rule made of hyphens', '<p>---</p>', '---'],
        ['lists and line breaks', '<ul><li>One</li><li>Two</li></ul>Line<br>Next', '- One\n- Two\n\nLine\nNext'],
        ['joiners in visible text', '<p>👩&#8205;💻 می&#8204;خواهم</p>', '👩\u200d💻 می\u200cخواهم'],
        [
            'preformatted text',
            '<pre>def run():\n    export(1)\n\n\tend</pre><p>Done</p>',
            'def run():\n    export(1)\n\n\tend\n\nDone',
        ],
        ['an image with only joiners beside it', '<img src="banner.png"><p>&#8204;&#8205; </p>', ''],
        ['an image-only list item', '<ul><li><img src="banner.png"></li></ul>', ''],
        ['html nested deeper than the stack allows', '<div>'.repeat(20000) + 'Hi' + '</div>'.repeat(20000), ''],
        ['table cells', '<table><tr><td>Total</td><td>$5</td></tr></table>', 'Total\n$5'],
    ])('renders %s', (_case, html, expected) => {
        expect(plainTextFromHtml(html)).toBe(expected)
    })
})
