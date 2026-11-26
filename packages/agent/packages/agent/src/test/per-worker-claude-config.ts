import { tmpdir } from "node:os";
import { resolve } from "node:path";

process.env.CLAUDE_CONFIG_DIR = resolve(
  tmpdir(),
  `posthog-agent-test-claude-${process.env.VITEST_POOL_ID ?? "0"}`,
);
