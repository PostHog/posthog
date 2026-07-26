# Canvas application builds

Canvas source and build records are control-plane metadata in PostgreSQL. The
complete, compressed source project is stored privately under
`canvas/source/<team>/sha256/…` in the configured object-storage bucket. Built
HTML, JavaScript, and CSS are immutable objects under
`canvas/artifacts/<team>/<build>/…`. Source archives are never served by the
artifact endpoint.

The `build_canvas` Celery task invokes the pinned Node builder shipped in the
main Django image. The builder accepts the fixed source-project schema, disables
package lifecycle scripts, bundles without executing canvas source, and emits a
bounded manifest that the worker independently verifies before upload. A ready
build becomes active only while its source version is still the canvas head;
failed and stale builds cannot replace the last-known-good artifact.

Production requires both settings below:

- `CANVAS_ARTIFACT_ORIGIN`: an HTTPS origin dedicated to untrusted user content,
  with requests for `/canvas-artifacts/*` routed to Django. It must not share the
  PostHog application host or its cookies.
- `CANVAS_ARTIFACT_SIGNING_KEYS`: comma-separated secrets of at least 32 bytes,
  newest first. Keep old keys during rotation until issued five-minute artifact
  URLs have expired.

Token generation and artifact serving fail closed when either production
requirement is absent. The artifact endpoint also rejects requests received on
a host other than the configured user-content origin. Canvases run in an
`allow-scripts` iframe without same-origin access, with a generated CSP and a
manifest-enforced PostHog bridge. Direct external network capabilities remain
disabled until a user-facing capability approval flow exists.

The daily `collect_canvas_objects` task retains all source history, the active
and previous builds, and pinned builds. It removes other build artifacts after
30 days and deletes unreferenced source or artifact objects after a 24-hour
recovery window. Hosted functions, secrets, databases, and serverless backends
are future work and are not part of this runtime.
