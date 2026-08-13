import { registerRendererStateStorage } from "@posthog/ui/shell/rendererStorage";
import { rawLocalStorage } from "./web-local-store";

// Web persistence backend for @posthog/ui stores (drafts, settings, layout).
// Desktop persists through the host; web uses origin-scoped localStorage via the
// shared seam (web-local-store).
registerRendererStateStorage(rawLocalStorage);
