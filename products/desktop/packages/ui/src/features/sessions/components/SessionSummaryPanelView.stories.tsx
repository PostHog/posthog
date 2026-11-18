import { CHAT_CONTENT_MAX_WIDTH } from "@posthog/ui/features/sessions/constants";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SessionSummaryPanelView } from "./SessionSummaryPanelView";

const SUMMARY = `**Goal.** Ship the JSONL parser behind the \`parser-v2\` flag.

**Progress.** The reader streams lines and the tests pass locally. The flag is off in production.

**Files.** \`src/parse/jsonl.ts\`, \`src/parse/jsonl.test.ts\`, \`src/flags.ts\`.

**Next.** Wire the flag into the ingest path, then measure the parse time on a large file.

**Blocker.** The staging bucket rejects uploads over 50 MB, so the large-file measurement is untested.`;

const LONG_SUMMARY = `**Goal.** Replace the hand-rolled JSONL reader with a streaming parser behind the \`parser-v2\` flag, without changing what the ingest path writes.

**Constraints.** The old reader stays the default until the flag rolls out. Output rows must match byte for byte, because the downstream table is append-only.

**Decisions.** The parser reads line by line instead of buffering the whole file, so a malformed line fails on its own rather than killing the run. Errors carry the line number. The flag is read once per run, not per line.

**Progress.** The parser and its tests are done. The suite covers empty files, a trailing newline, a line over the size cap, and invalid UTF-8. All of it passes locally.

**Files.** \`src/parse/jsonl.ts\` holds the parser. \`src/parse/jsonl.test.ts\` holds the cases. \`src/flags.ts\` declares the flag. \`src/ingest/run.ts\` still calls the old reader.

**Commands.** \`pnpm test src/parse\` runs the parser tests. \`pnpm typecheck\` is clean.

**Remaining work.** Wire the flag into \`src/ingest/run.ts\`, keep the old path as the fallback, then measure the parse time on a file over one gigabyte. After that, remove the old reader in a separate change.

**Blockers.** The staging bucket rejects uploads over 50 MB, so the large-file measurement has no input yet. Ask for a raised limit, or generate the file inside the sandbox instead.`;

const meta: Meta<typeof SessionSummaryPanelView> = {
  title: "Sessions/SessionSummaryPanelView",
  component: SessionSummaryPanelView,
  args: {
    title: "Session summary",
    onCopy: () => {},
    onRetry: () => {},
    onDismiss: () => {},
  },
  decorators: [
    (Story) => (
      <div className="mx-auto p-4" style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof SessionSummaryPanelView>;

export const Writing: Story = {
  args: { state: { status: "pending" } },
};

export const Written: Story = {
  args: { state: { status: "done", summary: SUMMARY } },
};

/** The scroll-heavy case: the text outgrows the panel and the edge fades. */
export const LongSummary: Story = {
  args: { state: { status: "done", summary: LONG_SUMMARY } },
};

export const Failed: Story = {
  args: {
    state: { status: "error", error: "The session is not connected." },
  },
};
