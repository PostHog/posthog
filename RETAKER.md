## Retaker (Browser capture) – Step-by-step Implementation Plan

Goal: enable heatmap captures for authenticated/internal pages and sites that block iframes by capturing in the user’s browser, then uploading the stitched full-page image(s) to store as `HeatmapSnapshot`.

### Progress

- [x] Backend model updated: `HeatmapSnapshot.source` and `HeatmapSnapshot.captured_at`
- [x] Backend JWT audience added: `HEATMAP_RETAKER_UPLOAD`
- [x] Backend endpoints:
  - [x] `POST saved/:short_id/retaker/token` – returns short‑lived upload token
  - [x] `POST saved/:short_id/retaker/upload` – accepts JPEG/PNG upload, stores snapshot with `source` and `captured_at`
- [ ] Frontend UX scaffolding: add Retaker option and CTAs
- [x] Frontend UX scaffolding: add Retaker option and placeholder panel in detail view
- [x] Frontend: token request flow (Generate token button; shows token/expiry/widths)
- [x] Frontend: manual upload UI (file input using token)
- [ ] Frontend: bookmarklet instructions (copyable)
- [ ] Chrome extension (multi-width) and integration
- [ ] Docs/telemetry/polish

### 0) Scope and non-goals

- In scope: On-demand capture in the user’s browser (bookmarklet first, browser extension next), multiple widths, scroll-and-stitch, short‑lived signed uploads, UI integration.
- Not in scope (initially): Scheduled/autonomous recapture of authed pages without user present; full DOM capture; code execution replay.

### 1) User stories and UX

1. New heatmap creation:
   - User enters URL, sees “Capture method” options: Screenshot (server), Iframe, Browser capture (Retaker).
   - If iframe is blocked or server screenshot looks like a login page, UI recommends Browser capture with a CTA.
2. Existing heatmap:
   - A “Retake in browser” button per width allows re-capture and upload.
3. Progress and result:
   - Show capture progress (tiles/widths), upload progress, and final thumbnails. Prefer browser-captured snapshot for display if present for a width.

### 2) Deliver in phases

#### Phase 0 – UX scaffolding

1. Add “Browser capture (Retaker)” option to the creation flow and heatmap detail page.
2. Add detection + guidance:
   - Iframe preflight fails → suggest Browser capture.
   - Server screenshot looks like auth/login → suggest Browser capture.
3. Add CTA(s): “Capture current page”, “Learn how to use Retaker”.

#### Phase 1 – Bookmarklet MVP (single width)

1. Token issuance (backend):
   - Endpoint to mint a short‑lived, scoped upload token for a specific `heatmap_id` and one or more widths. Expiry: 5–10 minutes; optional single-use.
2. Upload endpoint (backend):
   - Accepts image (JPEG), `heatmap_id`, `width`, `source=browser_bookmarklet` using the token. Validate team access, size limits, MIME, and width constraints.
   - Persist via existing `HeatmapSnapshot` (see data model updates below).
3. Data model updates:
   - Add `source` enum on `HeatmapSnapshot` (e.g., `server`, `browser_bookmarklet`, `browser_extension`).
   - Add `captured_at` timestamp (defaults to `now()`), backfill existing where needed.
4. Bookmarklet UX:
   - UI shows one-click bookmarklet generator bound to the target heatmap and widths (or just current width for MVP) and instructions.
   - Flow: User navigates to a target page (logged in), clicks bookmarklet → capture runs → uploads using the token.
5. Capture behavior (high-level, no code):
   - Prewarm by scrolling the page to trigger lazy loading; compute final document height.
   - Scroll in steps with overlap; capture each viewport tile; stitch into a single JPEG; upload.
6. Error handling & limits:
   - If canvas height limits are exceeded, split into chunks and upload multiple segments (server stitches or we store segments per width).
   - Show clear errors (e.g., CORS/tainted canvas); recommend extension for reliability.

#### Phase 2 – Chrome extension (robust, multi-width)

1. Extension architecture:
   - Minimal permissions: `activeTab`, `tabs`, `scripting`, `storage`.
   - Background service worker handles `captureVisibleTab`; content script orchestrates scrolling and metrics; options page for configuration/testing.
2. Multi-width capture:
   - Resize the window to achieve target CSS pixel width(s) (compensate for OS chrome and scrollbars), then repeat scroll-and-capture per width.
3. Reliability improvements:
   - Use native raster screenshots (not DOM rendering) → avoids CORS/taint. Inject temporary CSS to disable animations and hide overlays.
4. Upload integration:
   - Reuse Phase 1 token and upload endpoints with `source=browser_extension`.
5. UX integration:
   - “Open in Retaker” button launches instructions: mint token, open target page, start capture.

#### Phase 3 – Optional advanced: server capture with ephemeral cookies

1. Provide an advanced flow for scheduled capture:
   - User pastes exported cookies for domain → encrypt at rest; run a one-off Playwright job; delete cookies after capture. Clearly warn about risks.
2. Scheduling remains off by default for authed pages; require explicit opt-in.

#### Phase 4 – Polish and additional platforms

1. Firefox extension parity.
2. Optional: best-effort multi-width in bookmarklet.
3. Snippet-powered capture (if PostHog snippet is present on the site) for simplified orchestration.

### 3) Backend changes (detailed)

1. Endpoints:
   - POST `/api/heatmaps/{id}/retaker/token` → returns JWT token scoped to `heatmap_id` and widths; includes expiry and optional single-use claim.
   - POST `/api/heatmaps/{id}/snapshots/upload` → headers or query include width & source; body is JPEG blob.
2. Validation and limits:
   - Team & project auth; token scope; max image size; allowed widths; max number of widths per session.
   - Deduplicate uploads by `(heatmap_id,width,hash)`; accept idempotent retries.
3. Data model:
   - `HeatmapSnapshot`: add `source` (enum), `captured_at` (datetime). Consider optional chunk/segment storage for very tall pages if server-side stitching is chosen later.
4. Display selection:
   - When both `server` and `browser_*` exist for the same width, prefer `browser_*` for display while keeping both.
5. Observability:
   - Structured logs, metrics for token issuance, upload successes/failures, image dimensions, and dedupe hits.

### 4) Frontend changes (detailed)

1. UI updates:
   - Add “Browser capture (Retaker)” as a third capture method in creation flow.
   - On heatmap detail, show “Retake in browser” and width selectors.
2. Heuristics:
   - Iframe blocked (CSP/X-Frame-Options) → suggest Retaker.
   - Server screenshot looks like login (heuristics: presence of password inputs, page title patterns) → suggest Retaker.
3. Token flow:
   - Request token(s) for selected widths; display clear expiry; handle refresh.
4. Bookmarklet UX:
   - Render a drag-to-bookmarks button and short instructions; show copyable fallback.
5. Extension UX:
   - Instructions to install; button to mint token and start capture; show progress/status.
6. Progress & results:
   - Modal/toast with capture progress (per tile/width) and upload progress; refresh snapshots on success.

### 5) Capture algorithm (behavioral spec)

1. Compute page metrics (width/height, viewport size, DPR) consistently with server logic.
2. Prewarm: scroll to bottom with small delays to trigger lazy loads; recompute final height.
3. Tile capture loop: scroll in steps (`viewportHeight - overlap`), small delay per step, capture each tile.
4. Stitch: draw tiles at the correct scaled offsets; handle very tall pages by chunking if needed.
5. Quality: JPEG at 70–85; white background; strip metadata.
6. Overlays: temporarily hide cookie/consent overlays and disable animations during capture.

### 6) Security & privacy

1. Short-lived, scoped upload tokens; optional single-use; strict server validation.
2. No cookie exfiltration in Retaker flows; only raster images leave the tab.
3. Explicit user action required to start capture; show warning that sensitive page content will be included.
4. Rate limits and size limits on uploads; store images under existing access controls.

### 7) Testing plan

1. Unit tests: token issuance and validation, upload endpoint validation, dedupe behavior.
2. Integration tests: end-to-end upload storing `HeatmapSnapshot` with new fields; display precedence logic.
3. Manual/E2E matrix:
   - Authed app (behind login), public site, site with iframe blocks; mobile/desktop breakpoints; high DPR; very tall pages; sticky headers.
4. Extension manual tests: window resizing accuracy per width; capture correctness; progress and failure UX.

### 8) Rollout & metrics

1. Rollout: Phase 0 (UX), Phase 1 (bookmarklet) to everyone; Phase 2 (extension) behind a feature flag then GA.
2. Metrics: rate of successful captures by method, reasons for fallback, average capture time, upload sizes, errors by class.
3. Docs: update Heatmaps docs with instructions and limitations; inline help links from UI.

### 9) Risks and mitigations

1. Bookmarklet tainted canvas (CORS): document limitation; recommend extension.
2. Extremely tall pages: chunk captures; consider server-side stitching later.
3. Sticky elements and seams: higher overlap; temporary CSS to neutralize fixed/sticky; visual QA.
4. Token replay/abuse: short expiries, single-use tokens, server-side dedupe.

### 10) Acceptance criteria

- Users can capture a full-page image of an authed page via Retaker and see it in the heatmap view for at least one width.
- Uploads are authenticated via short-lived tokens and stored as `HeatmapSnapshot` with `source=browser_*`.
- UI suggests Retaker when iframe is blocked or server screenshot shows login.
- Chrome extension supports multi-width capture reliably; bookmarklet works for a meaningful subset of sites.
