// @ts-nocheck
// Test fixture for tooltip-link-needs-doclink-or-interactive rule.
//
// Mirrors the three shapes the rule matches:
//   1. Link as the bare value of title
//   2. Link inside a Fragment <>...</>
//   3. Link inside a single element wrapper (span/div/p/etc.)
//
// Plus the negative cases the rule must NOT match (false-positive guards).

import { Link, Tooltip } from '@posthog/lemon-ui'

// ─── ruleid cases: <Tooltip> with <Link> inside `title` and no docLink/interactive ───

// ruleid: tooltip-link-needs-doclink-or-interactive
function Case1Fragment() {
    return (
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
}

// ruleid: tooltip-link-needs-doclink-or-interactive
function Case2SpanWrap() {
    return (
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
}

// ruleid: tooltip-link-needs-doclink-or-interactive
function Case3DivWrap() {
    return (
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
}

// ruleid: tooltip-link-needs-doclink-or-interactive
function Case4BareLink() {
    return (
        <Tooltip title={<Link to="https://posthog.com/docs/foo">Just a link</Link>}>
            <IconInfo />
        </Tooltip>
    )
}

// ruleid: tooltip-link-needs-doclink-or-interactive
// The `closeDelayMs` workaround does NOT satisfy interactive — it extends the
// close timer but the popup is still not hoverable. Rule must still match.
function Case5CloseDelayWorkaround() {
    return (
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
}

// ruleid: tooltip-link-needs-doclink-or-interactive
// Link nested two layers deep — must still match. Six of the eleven audited
// bug cases had this shape.
function Case6DeeplyNested() {
    return (
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
}

// ruleid: tooltip-link-needs-doclink-or-interactive
// Plain <a href> inside title — must also match (Link is the common case in the
// audit, but the rule covers bare anchors too).
function Case7PlainAnchor() {
    return (
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
}

// ─── ok cases: rule must NOT match ───

// ok: tooltip-link-needs-doclink-or-interactive
// docLink set → rule must not match
function OkWithDocLink() {
    return (
        <Tooltip docLink="https://posthog.com/docs/foo" title="Some prose.">
            <IconInfo />
        </Tooltip>
    )
}

// ok: tooltip-link-needs-doclink-or-interactive
// interactive set (bare) → rule must not match
function OkInteractiveBare() {
    return (
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
}

// ok: tooltip-link-needs-doclink-or-interactive
// interactive={true} → rule must not match
function OkInteractiveExplicit() {
    return (
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
}

// ok: tooltip-link-needs-doclink-or-interactive
// Link is the *trigger* (children), not inside title → rule must not match
function OkLinkIsTrigger() {
    return (
        <Tooltip title="Hover me">
            <Link to="/somewhere">Click me</Link>
        </Tooltip>
    )
}

// ok: tooltip-link-needs-doclink-or-interactive
// Plain-string title, no Link anywhere → rule must not match
function OkPlainStringTitle() {
    return (
        <Tooltip title="Just a label">
            <span>trigger</span>
        </Tooltip>
    )
}

// ok: tooltip-link-needs-doclink-or-interactive
// Title JSX without a Link → rule must not match
function OkRichTextNoLink() {
    return (
        <Tooltip title={<span className="font-mono">code-ish content</span>}>
            <IconInfo />
        </Tooltip>
    )
}

// nosemgrep: tooltip-link-needs-doclink-or-interactive
// Suppressed call site. Documenting why suppression is acceptable should sit
// adjacent to the nosemgrep comment in real code.
function SuppressedIntentionally() {
    return (
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
}
