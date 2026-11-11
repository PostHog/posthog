import { describe, expect, it } from "vitest";
import { buildSandboxDocument } from "./sandboxRuntime";

// The web app cannot load the sandbox as srcdoc, because a srcdoc frame
// inherits the app's CSP. Django serves this checked-in copy from the canvas
// artifact origin instead. Run `pnpm --filter @posthog/ui
// generate-web-sandbox` to write it again after a change to sandboxRuntime.ts.
const WEB_SANDBOX_DOCUMENT =
  "../../../../../../../canvas/backend/sandbox/sandbox_document.html";

describe("web sandbox document", () => {
  it("matches the copy Django serves", async () => {
    await expect(buildSandboxDocument()).toMatchFileSnapshot(
      WEB_SANDBOX_DOCUMENT,
    );
  });
});
