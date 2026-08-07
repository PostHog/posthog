import type { SyncedCustomInstructions } from "@posthog/ui/features/settings/settingsStore";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { PersonalizationSettingsView } from "./PersonalizationSettings";

const syncedFile = (
  overrides: Partial<SyncedCustomInstructions> = {},
): SyncedCustomInstructions => ({
  path: "/Users/paul/.claude/CLAUDE.md",
  displayPath: "~/.claude/CLAUDE.md",
  content: [
    "# My preferences",
    "",
    "- Always write tests for new code.",
    "- Prefer functional patterns.",
    "- Keep explanations terse; link to code instead of quoting it.",
    "- Never force-push shared branches.",
  ].join("\n"),
  truncated: false,
  ...overrides,
});

const meta: Meta<typeof PersonalizationSettingsView> = {
  title: "Settings/PersonalizationSettings",
  component: PersonalizationSettingsView,
  args: {
    instructions: "",
    onInstructionsChange: () => {},
    onInstructionsBlur: () => {},
    syncFromFile: false,
    onSyncToggle: () => {},
    synced: null,
  },
  // Match the settings dialog's content column so rows size realistically.
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 640, margin: "2rem auto", padding: "0 1rem" }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof PersonalizationSettingsView>;

/** Sync off: the editable box with its character counter. */
export const Default: Story = {
  args: {
    instructions:
      "Always write tests for new code. Prefer functional patterns.",
  },
};

/** Sync off with nothing typed yet: placeholder text and a 0/2000 counter. */
export const Empty: Story = {};

/**
 * Sync on and a CLAUDE.md was found: the box is disabled and greyed out (the
 * typed draft stays visible but inactive) and the caption names the file in
 * use.
 */
export const SyncedFromClaudeMd: Story = {
  args: {
    instructions:
      "These typed instructions are ignored while sync is on — the file wins.",
    syncFromFile: true,
    synced: syncedFile(),
  },
};

/** An AGENTS.md outranks CLAUDE.md; the caption shows which file won. */
export const SyncedFromAgentsMd: Story = {
  args: {
    syncFromFile: true,
    synced: syncedFile({
      path: "/Users/paul/.agents/AGENTS.md",
      displayPath: "~/.agents/AGENTS.md",
    }),
  },
};

/** The synced file blew past the 20k-char cap: the caption flags truncation. */
export const SyncedTruncated: Story = {
  args: {
    syncFromFile: true,
    synced: syncedFile({ truncated: true }),
  },
};

/**
 * Sync on but no file exists: an amber warning explains nothing is synced;
 * the box stays disabled because the typed instructions don't apply either.
 */
export const SyncOnNoFileFound: Story = {
  args: {
    instructions: "Typed instructions that are inactive while sync is on.",
    syncFromFile: true,
    synced: null,
  },
};
