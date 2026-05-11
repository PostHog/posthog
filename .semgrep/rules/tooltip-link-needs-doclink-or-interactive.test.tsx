// @ts-nocheck
// Test fixture for tooltip-link-needs-doclink-or-interactive rule.
//
// Semgrep test convention: `// ruleid:` / `// ok:` annotates the line
// IMMEDIATELY AFTER the comment, and the rule's match start line must be
// that next line. For JSX patterns, the match starts on the `<Tooltip` line,
// so each annotation sits directly above `<Tooltip` — never above an outer
// wrapper like `function` or `return (`.

import { Link, Tooltip } from '@posthog/lemon-ui'

// ─── ruleid cases: <Tooltip> with <Link>/<a> inside `title`, missing both
//     `interactive` and `docLink`. Rule must match each one. ───

// Shape 1: Link inside a Fragment <>...</>
const Case1Fragment = (
    // ruleid: tooltip-link-needs-doclink-or-interactive
    <Tooltip
        title={
            <>
                Some prose. <Link to="https://posthog.com/docs/foo">Learn more</Link>
            </>
        }
    >
        <span>trigger</span>
    </Tooltip>
)

// Shape 2: Link inside a <span> wrapper
const Case2SpanWrap = (
    // ruleid: tooltip-link-needs-doclink-or-interactive
    <Tooltip
        title={
            <span>
                Body copy. Read about <Link to="https://posthog.com/docs/foo">the thing</Link>.
            </span>
        }
    >
        <IconInfo />
    </Tooltip>
)

// Shape 3: Link inside a <div> wrapper
const Case3DivWrap = (
    // ruleid: tooltip-link-needs-doclink-or-interactive
    <Tooltip
        title={
            <div>
                Paragraph one. <Link to="https://posthog.com/docs/foo">Docs</Link>.
            </div>
        }
    >
        <IconInfo />
    </Tooltip>
)

// Shape 4: Link as the bare value of `title`
const Case4BareLink = (
    // ruleid: tooltip-link-needs-doclink-or-interactive
    <Tooltip title={<Link to="https://posthog.com/docs/foo">Just a link</Link>}>
        <IconInfo />
    </Tooltip>
)

// Shape 5: `closeDelayMs` workaround — extends the close timer but does NOT
// make the popup hoverable. Rule must still fire.
const Case5CloseDelayWorkaround = (
    // ruleid: tooltip-link-needs-doclink-or-interactive
    <Tooltip
        closeDelayMs={200}
        title={
            <>
                Body. <Link to="https://posthog.com/docs/foo">Docs</Link>
            </>
        }
    >
        <IconInfo />
    </Tooltip>
)

// Shape 6: Link nested two layers deep — six of the eleven audited bug
// cases had this shape.
const Case6DeeplyNested = (
    // ruleid: tooltip-link-needs-doclink-or-interactive
    <Tooltip
        title={
            <div className="deprecated-space-y-2">
                <div>Top-level prose.</div>
                <div>
                    Read more in the <Link to="https://posthog.com/docs/foo">documentation</Link>.
                </div>
            </div>
        }
    >
        <IconInfo />
    </Tooltip>
)

// Shape 7: Plain `<a href>` inside title — the rule covers bare anchors too,
// not just `<Link>`.
const Case7PlainAnchor = (
    // ruleid: tooltip-link-needs-doclink-or-interactive
    <Tooltip
        title={
            <>
                See <a href="/somewhere">over here</a>
            </>
        }
    >
        <IconInfo />
    </Tooltip>
)

// ─── ok cases: rule must NOT match (false-positive guards) ───

// `docLink` set
const OkWithDocLink = (
    // ok: tooltip-link-needs-doclink-or-interactive
    <Tooltip docLink="https://posthog.com/docs/foo" title="Some prose.">
        <IconInfo />
    </Tooltip>
)

// `interactive` set as bare prop
const OkInteractiveBare = (
    // ok: tooltip-link-needs-doclink-or-interactive
    <Tooltip
        interactive
        title={
            <>
                Body. <Link to="https://posthog.com/docs/foo">Docs</Link>
            </>
        }
    >
        <IconInfo />
    </Tooltip>
)

// `interactive={true}`
const OkInteractiveExplicit = (
    // ok: tooltip-link-needs-doclink-or-interactive
    <Tooltip
        interactive={true}
        title={
            <>
                Body. <Link to="/settings">Internal link</Link>
            </>
        }
    >
        <IconInfo />
    </Tooltip>
)

// `<Link>` is the trigger (children), not inside `title`
const OkLinkIsTrigger = (
    // ok: tooltip-link-needs-doclink-or-interactive
    <Tooltip title="Hover me">
        <Link to="/somewhere">Click me</Link>
    </Tooltip>
)

// Plain-string title, no Link anywhere
const OkPlainStringTitle = (
    // ok: tooltip-link-needs-doclink-or-interactive
    <Tooltip title="Just a label">
        <span>trigger</span>
    </Tooltip>
)

// Title JSX without a Link
const OkRichTextNoLink = (
    // ok: tooltip-link-needs-doclink-or-interactive
    <Tooltip title={<span className="font-mono">code-ish content</span>}>
        <IconInfo />
    </Tooltip>
)

// Suppressed call site — escape hatch for intentional non-hoverable cases.
// In real code, document the reason adjacent to the nosemgrep comment.
const SuppressedIntentionally = (
    // nosemgrep: tooltip-link-needs-doclink-or-interactive
    <Tooltip
        title={
            <>
                Decorative <Link to="https://posthog.com/docs/foo">link</Link> that nobody clicks
            </>
        }
    >
        <IconInfo />
    </Tooltip>
)
