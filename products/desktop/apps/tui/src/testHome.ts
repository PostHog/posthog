import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Components read and write ~/.config/posthog-tui, and test files run in parallel, so each file gets its own home.
process.env.HOME = mkdtempSync(join(tmpdir(), "posthog-tui-home-"));
