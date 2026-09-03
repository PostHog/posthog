# Remote in-app announcements

Broad in-app announcements are **remote content, not code**. They live in the
JSON payload of the `posthog-desktop-announcements` feature flag (PostHog
project 2) and render through `packages/ui/src/features/announcements/`.
Publishing, changing, or retiring an announcement means editing that flag
payload — never adding a component. The employee-gated editor is
https://desktop-announcements-admin.hosthog.dev (`tools/announcements-admin/`).

**Do not build new ad-hoc announcement surfaces** (flag-gated promo cards,
dismissible banners, one-time modals). That is a Forbidden Pattern in
AGENTS.md. The only announcement-adjacent surfaces outside this system are
the What's New changelog and the update modals.

## How it works

- The payload schema is `packages/shared/src/announcements.ts`
  (`announcementsPayloadSchema`) — shared so authoring tools validate with the
  exact schema the app parses. Items are validated one by one: a malformed
  entry drops alone and is counted, never crashing the batch.
- `selectAnnouncement.ts` is the pure decision function: Zod parse → time
  window (`startsAt`/`endsAt`) → version gate → per-id dismissals → priority.
  It returns nothing for development builds or when the app version is unknown,
  which keeps local development and the web host (no `os.getAppVersion`)
  announcement-free by construction.
- Dismissals persist per announcement `id` in `announcementsStore.ts`;
  changing an announcement's `id` resurfaces it for everyone.
- Surfaces: `AnnouncementBanner` (top of the framed content pane in
  `__root.tsx` — overlays the content, never the sidebar) and
  `AnnouncementsHost` (the modal surfaces, mounted in the shell beside the
  update modals).
- Modals open with a hero band (`AnnouncementHero`, styled after the Loops
  promo dialog): a hedgehog on a colored band by default, overridable per item
  via `hero` — `{ "hedgehog": "<slug>", "color": "#rrggbb" }`,
  `{ "imageUrl": "https://…" }`, or `{ "none": true }` for a plain modal.
  The slug is a bundled name (`builder`, `explorer`, `happy`, `loop` — local
  assets, no network) or any hoggie PNG file name from
  [PostHog/brand](https://brand.posthog.com/hoggies) — variants are
  file-name-suffixed (`wizard-3`, `dadd-ai-1`), so the metadata slug alone is
  not always a valid name; the admin editor's picker lists exactly the valid
  ones. Non-bundled names load from a CDN copy pinned to the package release
  (`hoggiePngUrl`) with a fallback to the default hedgehog when unreachable.
  Banners never render a hero.

## The two kinds

- `kind: "announcement"` — a feature announcement everyone sees,
  `style: "banner" | "modal"`. Optional `minVersion` means "the announced
  feature needs at least this version": apps below it get an "Update now"
  action (`UpdateAction`) in place of the `cta`; apps at or above it get the
  `cta`. Dismissible unless `requiresAck`.
  - `requiresAck: true` (modal only — the schema rejects banners) blocks
    until the user explicitly acts: no dismiss, no Esc, and the app's
    keyboard shortcuts are suspended while it is on stage
    (`useBlockingKeyboardIsolation` — `required-update` gets the same
    isolation). Up-to-date users get
    the ack button (`ackLabel`, default "OK"); users below `minVersion` get
    the update action instead, and **updating counts as acknowledging** — the
    ack records when the restart-to-install handoff begins, so a failed or
    abandoned download keeps the announcement blocking. The manual-download
    link (updater-less platforms) never acknowledges; after relaunching on a
    new-enough version the ack button shows instead.
- `kind: "required-update"` — shown **only** to apps below its required
  `minVersion`: a blocking, non-dismissible modal (`RequiredUpdateModal`)
  that drives the existing update flow. Users already up to date never see
  it. For "everyone must confirm they saw this" use
  `announcement` + `requiresAck` instead.

## Precedence

One announcement per app session: the first unmet `required-update` in
payload order, else the first eligible `announcement`. Dismissing or
acknowledging one retires announcements for the rest of the session — the
next eligible item waits for the next launch, so overlapping announcements
never show back to back. Required updates are exempt: one still blocks even
after an announcement was handled in the same session.

## CTA rules

`cta.url` is either `https://…` (opens the default browser) or a
`posthog-code://…` deep link, which dispatches **in-app** via the
`deepLink.open` tRPC forward to the main-process handler — no OS hop, no
browser. Author payloads with the production scheme; `announcementCta.ts`
swaps in the dev scheme on dev builds.

## Observability

The app captures these events with `announcement_id`, `announcement_kind`, and
`announcement_style` properties. CTA clicks add `cta_type`; acknowledgements
add `ack_type`.

- `Announcement shown`
- `Announcement CTA clicked`
- `Announcement dismissed`
- `Announcement acknowledged`

Filter these events by an announcement ID to measure unique people shown,
CTA engagement, dismissals, and acknowledgements.

## Testing

Development builds intentionally never render remote announcements, including
feature-flag overrides. Exercise the selection behavior through
`selectAnnouncement.test.ts` and the announcement component stories. Use a
production build to smoke-test a live flag payload.
