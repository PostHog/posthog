// @ts-nocheck
// Test fixture for tooltip-link-needs-doclink-or-interactive rule.
//
// Each test case is a single-line JSX expression assigned to a const so the
// annotation comment is on the line directly above the matched expression.
// The rule matches the Tooltip JSX element; Semgrep reports the match start
// at the line where that element's expression begins.

import { Link, Tooltip } from '@posthog/lemon-ui'

// ─── Positive cases — rule must match ───

// Shape 1: Link inside a Fragment wrapper.
// ruleid: tooltip-link-needs-doclink-or-interactive
const Case1Fragment = <Tooltip title={<>Some prose. <Link to="https://posthog.com/docs/foo">Learn more</Link></>}><span>trigger</span></Tooltip>

// Shape 2: Link inside a <span> wrapper.
// ruleid: tooltip-link-needs-doclink-or-interactive
const Case2SpanWrap = <Tooltip title={<span>Body copy. Read about <Link to="https://posthog.com/docs/foo">the thing</Link>.</span>}><IconInfo /></Tooltip>

// Shape 3: Link inside a <div> wrapper.
// ruleid: tooltip-link-needs-doclink-or-interactive
const Case3DivWrap = <Tooltip title={<div>Paragraph one. <Link to="https://posthog.com/docs/foo">Docs</Link>.</div>}><IconInfo /></Tooltip>

// Shape 4: Link as the bare value of title.
// ruleid: tooltip-link-needs-doclink-or-interactive
const Case4BareLink = <Tooltip title={<Link to="https://posthog.com/docs/foo">Just a link</Link>}><IconInfo /></Tooltip>

// Shape 5: closeDelayMs workaround — extends the close timer but does NOT
// make the popup hoverable, so the rule must still fire.
// ruleid: tooltip-link-needs-doclink-or-interactive
const Case5CloseDelayWorkaround = <Tooltip closeDelayMs={200} title={<>Body. <Link to="https://posthog.com/docs/foo">Docs</Link></>}><IconInfo /></Tooltip>

// Shape 6: Link nested two layers deep — six of the eleven audited bug cases
// had this shape (nested <div> wrappers).
// ruleid: tooltip-link-needs-doclink-or-interactive
const Case6DeeplyNested = <Tooltip title={<div className="deprecated-space-y-2"><div>Top-level prose.</div><div>Read more in the <Link to="https://posthog.com/docs/foo">documentation</Link>.</div></div>}><IconInfo /></Tooltip>

// Shape 7: Plain <a href> inside title — the rule covers bare anchors too.
// ruleid: tooltip-link-needs-doclink-or-interactive
const Case7PlainAnchor = <Tooltip title={<>See <a href="/somewhere">over here</a></>}><IconInfo /></Tooltip>

// ─── Negative cases — rule must NOT match ───

// docLink set
// ok: tooltip-link-needs-doclink-or-interactive
const OkWithDocLink = <Tooltip docLink="https://posthog.com/docs/foo" title="Some prose."><IconInfo /></Tooltip>

// interactive set as a bare prop
// ok: tooltip-link-needs-doclink-or-interactive
const OkInteractiveBare = <Tooltip interactive title={<>Body. <Link to="https://posthog.com/docs/foo">Docs</Link></>}><IconInfo /></Tooltip>

// interactive={true} — explicit truthy value
// ok: tooltip-link-needs-doclink-or-interactive
const OkInteractiveExplicit = <Tooltip interactive={true} title={<>Body. <Link to="/settings">Internal link</Link></>}><IconInfo /></Tooltip>

// Link is the trigger (children), not inside title
// ok: tooltip-link-needs-doclink-or-interactive
const OkLinkIsTrigger = <Tooltip title="Hover me"><Link to="/somewhere">Click me</Link></Tooltip>

// Plain-string title, no Link anywhere
// ok: tooltip-link-needs-doclink-or-interactive
const OkPlainStringTitle = <Tooltip title="Just a label"><span>trigger</span></Tooltip>

// Title JSX without a Link
// ok: tooltip-link-needs-doclink-or-interactive
const OkRichTextNoLink = <Tooltip title={<span className="font-mono">code-ish content</span>}><IconInfo /></Tooltip>

// Suppressed call site — escape hatch for intentional non-hoverable cases.
// nosemgrep: tooltip-link-needs-doclink-or-interactive
const SuppressedIntentionally = <Tooltip title={<>Decorative <Link to="https://posthog.com/docs/foo">link</Link> that nobody clicks</>}><IconInfo /></Tooltip>
