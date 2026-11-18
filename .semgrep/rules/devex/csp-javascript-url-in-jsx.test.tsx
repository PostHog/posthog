// @ts-nocheck
// Test fixture for the csp-javascript-url-in-jsx rule.

// ruleid: csp-javascript-url-in-jsx
const Anchor = <a href="javascript:void(0)">Nothing</a>

// ruleid: csp-javascript-url-in-jsx
const MixedCaseInBraces = <a className="x" href={'JavaScript:go()'}>Mixed case</a>

// ruleid: csp-javascript-url-in-jsx
const TemplateLiteral = <a href={`javascript:${code}`}>Template</a>

// ruleid: csp-javascript-url-in-jsx
const Frame = <iframe src="javascript:''" sandbox="" />

// ruleid: csp-javascript-url-in-jsx
const FormAction = <form action="javascript:void(0)" />

// ruleid: csp-javascript-url-in-jsx
const SubmitterAction = <button formAction="javascript:go()">Save</button>

// Link strips the scheme, which leaves a dead link, so the rule still reports it.
// ruleid: csp-javascript-url-in-jsx
const RouterLink = <Link to="javascript:void(0)">Link</Link>

// ok: csp-javascript-url-in-jsx
const External = <a href="https://posthog.com/docs">Docs</a>

// ok: csp-javascript-url-in-jsx
const Dynamic = <a href={url}>Dynamic</a>

// ok: csp-javascript-url-in-jsx
const Handler = <LemonButton onClick={() => window.history.back()}>Back</LemonButton>

// ok: csp-javascript-url-in-jsx
const OtherAttribute = <CodeSnippet language="javascript:">{label}</CodeSnippet>

export function navigate(anchor: HTMLAnchorElement, url: string, code: string): void {
    // ruleid: csp-javascript-url-in-jsx
    anchor.href = 'javascript:void(0)'
    // ruleid: csp-javascript-url-in-jsx
    window.location = 'javascript:go()'
    // ruleid: csp-javascript-url-in-jsx
    location = 'javascript:go()'
    // ruleid: csp-javascript-url-in-jsx
    window.location.assign('javascript:go()')
    // ruleid: csp-javascript-url-in-jsx
    location.replace('javascript:go()')
    // ruleid: csp-javascript-url-in-jsx
    window.open(`javascript:${code}`, '_blank')
    // ruleid: csp-javascript-url-in-jsx
    open('javascript:go()')
    // ok: csp-javascript-url-in-jsx
    anchor.href = '/docs/javascript:intro'
    // ok: csp-javascript-url-in-jsx
    window.open(url, '_blank', 'noopener')
    // ok: csp-javascript-url-in-jsx
    const label = 'javascript: the language'
}
