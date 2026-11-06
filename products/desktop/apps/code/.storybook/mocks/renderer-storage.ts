import { registerRendererStateStorage } from "@posthog/ui/shell/rendererStorage";

/**
 * Persistence for stories. The desktop host registers this seam at boot and
 * apps/web registers localStorage; nothing registers it here, so a persisted
 * store's first read never settles and anything gated on rehydration (a
 * teaching tip that must not flash before it knows it was retired) stays
 * invisible in Storybook.
 *
 * In-memory rather than localStorage, so a story never inherits what an earlier
 * story wrote.
 */
const values = new Map<string, string>();

registerRendererStateStorage({
  getItem: (name) => values.get(name) ?? null,
  setItem: (name, value) => {
    values.set(name, value);
  },
  removeItem: (name) => {
    values.delete(name);
  },
});
