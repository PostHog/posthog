import { marked } from 'marked'

// `marked` passes raw HTML through to its output, unlike the app's renderer (`skipHtml`). Parsing
// escaped text with it checks the escape on its own: any markup left in the output after the
// tags `marked` generates itself came from raw HTML that the escape let through. The check reads
// the HTML string, because a DOM parser silently drops some raw HTML (`<body>`, stray closers).
// A link to an http(s) URL is generated too, by the autolink of a bare URL. Raw HTML that looks
// like one is caught by the visible text check, which would show the link label and not the tag.
const GENERATED_TAG =
    /<\/?(?:p|br|pre|blockquote|ul|li|h[1-6]|strong|em|del|hr|table|thead|tbody|tr)>|<code(?: class="language-[\w-]+")?>|<\/code>|<ol(?: start="\d+")?>|<\/ol>|<\/?t[hd](?: align="\w+")?>|<a href="https?:\/\/[^"]*">|<\/a>/g
const RAW_MARKUP = /<[a-zA-Z/!?][^]*?(?:>|$)/g

function renderedHtml(markdown: string): string {
    return marked.parse(markdown, { async: false })
}

export function unsafeMarkup(markdown: string): string[] {
    return renderedHtml(markdown).replace(GENERATED_TAG, '').match(RAW_MARKUP) ?? []
}

export function renderedElements(markdown: string): Element[] {
    const container = document.createElement('div')
    container.innerHTML = renderedHtml(markdown)
    return Array.from(container.querySelectorAll('*'))
}

export function renderedTags(markdown: string): string[] {
    return renderedElements(markdown).map((element) => element.tagName)
}

export function visibleText(markdown: string): string {
    const container = document.createElement('div')
    container.innerHTML = renderedHtml(markdown)
    return (container.textContent ?? '').trim()
}

export const XSS_PAYLOADS: [string, string][] = [
    ['script', '<script>alert(1)</script>'],
    ['uppercase script', '<SCRIPT>alert(1)</SCRIPT>'],
    ['mixed case script', '<ScRiPt>alert(1)</sCrIpT>'],
    ['script with src', '<script src="https://example.com/x.js"></script>'],
    ['script with an attribute on the next line', '<script\ndefer>alert(1)</script\t>'],
    ['script with tab before the bracket', '<script\t>alert(1)</script>'],
    ['unterminated script body', '<script>alert(1)'],
    ['unterminated script opener', '<script src=//example.com/x.js'],
    ['doubled bracket', '<<script>alert(1)//<</script>'],
    ['closer then opener', '</script><script>alert(1)</script>'],
    ['img onerror', '<img src=x onerror=alert(1)>'],
    ['img with slashes as separators', '<img/src=x/onerror=alert(1)>'],
    ['img across lines', '<img\nsrc=x\nonerror=alert(1)>'],
    ['img with unterminated opener', '<img src=x onerror=alert(1)//'],
    ['img with a bracket inside an attribute', '<img alt=">" src=x onerror=alert(1)>'],
    ['svg onload', '<svg onload=alert(1)>'],
    ['svg with slash separator', '<svg/onload=alert(1)>'],
    ['iframe with javascript url', '<iframe src="javascript:alert(1)"></iframe>'],
    ['iframe srcdoc', '<iframe srcdoc="<script>alert(1)</script>"></iframe>'],
    ['anchor with javascript url', '<a href="javascript:alert(1)">click</a>'],
    ['anchor with data url', '<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">x</a>'],
    ['body onload', '<body onload=alert(1)>'],
    ['details ontoggle', '<details open ontoggle=alert(1)>'],
    ['input onfocus', '<input autofocus onfocus=alert(1)>'],
    ['video source onerror', '<video><source onerror=alert(1)></video>'],
    ['form with javascript action', '<form action="javascript:alert(1)"><button>go</button></form>'],
    ['object', '<object data="javascript:alert(1)"></object>'],
    ['embed', '<embed src="javascript:alert(1)">'],
    ['style import', '<style>@import "https://example.com/x.css";</style>'],
    ['style onload', '<style onload=alert(1)></style>'],
    ['link stylesheet', '<link rel="stylesheet" href="https://example.com/x.css">'],
    ['meta refresh', '<meta http-equiv="refresh" content="0;url=javascript:alert(1)">'],
    ['base', '<base href="https://example.com/">'],
    ['math namespace', '<math><mtext><script>alert(1)</script></mtext></math>'],
    ['comment around script', '<!-- <script>alert(1)</script> -->'],
    ['empty comment trick', '<!--><script>alert(1)</script>-->'],
    ['cdata section', '<![CDATA[<script>alert(1)</script>]]>'],
    ['doctype', '<!DOCTYPE html><script>alert(1)</script>'],
    ['processing instruction', '<?xml version="1.0"?><script>alert(1)</script>'],
    ['custom element with handler', '<x-widget onclick=alert(1)>text</x-widget>'],
    ['closing tags only', '</div></body></html>'],
    ['marquee', '<marquee onstart=alert(1)>x</marquee>'],
    ['textarea breakout', '</textarea><script>alert(1)</script>'],
    ['template', '<template><script>alert(1)</script></template>'],
    ['bare url running into an img', 'https://example.com/a<img src=x onerror=alert(1)>'],
    ['bare url running into a script', 'https://example.com/a"><script>alert(1)</script>'],
    ['www url running into a script', 'www.example.com/a<script>alert(1)</script>'],
    ['bare url, a space, then an img', 'https://example.com/a <img src=x onerror=alert(1)>'],
    ['paragraph with a handler', '<p onclick=alert(1)>x</p>'],
    ['code with a handler', '<code onmouseover=alert(1)>x</code>'],
    ['pre with a style', '<pre style="position:fixed;inset:0">x</pre>'],
]
