import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import type { Task } from "@posthog/shared/domain-types";
import type { TaskStatusInput } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The card's status comes from live session/workspace state and a per-task tRPC
// query, none of which a unit test has. Stubbed at the module boundary, as
// ChannelItemRow.test.tsx does for the same reason.
const mocks = vi.hoisted(() => ({ status: null as TaskStatusInput | null }));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTaskStatus", () => ({
  useChannelTaskStatus: () => mocks.status,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFileTaskToChannel", () => ({
  useFileTaskToChannel: () => vi.fn(),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));

import {
  ChannelItemHoverCard,
  ChannelItemPreviewCardProvider,
} from "./ChannelItemHoverCard";
import type { TaskRowMenuProps } from "./TaskRowMenu";

function item(title: string, overrides: Partial<ChannelItemModel> = {}) {
  return {
    key: `task:${title}`,
    kind: "task",
    id: title,
    title,
    ts: Date.parse("2026-07-17T12:00:00.000Z"),
    createdAt: Date.parse("2026-07-16T12:00:00.000Z"),
    pinned: false,
    rawStatus: "completed",
    environment: "cloud",
    source: null,
    needsInput: false,
    unread: false,
    authorUser: null,
    authorName: null,
    authorUuid: "user-uuid",
    templateId: null,
    repository: null,
    branch: null,
    task: null,
    ...overrides,
  } satisfies ChannelItemModel;
}

function menuFor(model: ChannelItemModel): TaskRowMenuProps {
  return {
    kind: "task",
    id: model.id,
    title: model.title,
    isPinned: false,
    onTogglePin: () => {},
  };
}

/** A cloud run that finished a turn, which persists its closing prose. */
function taskWithFinalMessage(text: string): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Investigate signup drop-off",
    description: "",
    created_at: "2026-07-16T12:00:00.000Z",
    updated_at: "2026-07-17T12:00:00.000Z",
    origin_product: "user_created",
    latest_run: {
      id: "run-1",
      task: "task-1",
      team: 1,
      branch: null,
      status: "completed",
      log_url: "",
      error_message: null,
      output: { final_message: text },
      state: {},
      created_at: "2026-07-16T12:00:00.000Z",
      updated_at: "2026-07-17T12:00:00.000Z",
      completed_at: "2026-07-17T12:00:00.000Z",
    },
  };
}

function renderRows(models: ChannelItemModel[]) {
  return render(
    <Theme>
      <ChannelItemPreviewCardProvider>
        {models.map((model) => (
          <ChannelItemHoverCard
            key={model.key}
            item={model}
            menu={menuFor(model)}
          >
            <button type="button">{model.title}</button>
          </ChannelItemHoverCard>
        ))}
      </ChannelItemPreviewCardProvider>
    </Theme>,
  );
}

async function openCardOn(title: string) {
  await userEvent.hover(screen.getByRole("button", { name: title }));
  return screen.findByRole("button", { name: "Pin" }, { timeout: 2000 });
}

beforeEach(() => {
  mocks.status = null;
});

describe("ChannelItemHoverCard", () => {
  it("names the state in the row's own vocabulary, not the run's status", async () => {
    // `rawStatus: "completed"` — the card used to read this as a green "Ready"
    // badge while the row's dot said the opposite.
    mocks.status = { needsPermission: true };
    renderRows([item("Investigate signup drop-off")]);

    await openCardOn("Investigate signup drop-off");

    expect(screen.getByText("Needs your input")).not.toBeNull();
    expect(screen.queryByText("Ready")).toBeNull();
  });

  it("names what the row's badges mean, with the origin as a stated fact", async () => {
    mocks.status = { prState: "merged", originProduct: "slack" };
    renderRows([item("Investigate signup drop-off")]);

    await openCardOn("Investigate signup drop-off");

    expect(screen.getByText("Merged")).not.toBeNull();
    // Named by the column it sits in, so the badge drops its own "Source:".
    expect(screen.getByText("Source")).not.toBeNull();
    expect(screen.getByText("Slack")).not.toBeNull();
  });

  it("shows the last thing the agent said", async () => {
    mocks.status = {};
    renderRows([
      item("Investigate signup drop-off", {
        task: taskWithFinalMessage("Dropped the retry loop and opened a PR."),
      }),
    ]);

    await openCardOn("Investigate signup drop-off");

    expect(
      screen.getByText("Dropped the retry loop and opened a PR."),
    ).not.toBeNull();
  });

  // The point of the shared card: one popup for the whole list, so crossing to
  // another row moves it rather than opening a second one behind the delay.
  it("moves to the next row without waiting to open again", async () => {
    mocks.status = {};
    renderRows([item("First session"), item("Second session")]);
    await openCardOn("First session");

    await userEvent.hover(
      screen.getByRole("button", { name: "Second session" }),
    );

    // No `findBy`: the card is already showing the second row by the time the
    // pointer has arrived, which is what "already open" buys.
    const titles = screen.getAllByText("Second session");
    expect(titles).toHaveLength(2);
    expect(screen.getAllByText("First session")).toHaveLength(1);
  });

  it("leaves a row usable where no list is hosting a card", async () => {
    mocks.status = {};
    const model = item("Investigate signup drop-off");
    render(
      <Theme>
        <ChannelItemHoverCard item={model} menu={menuFor(model)}>
          <button type="button">{model.title}</button>
        </ChannelItemHoverCard>
      </Theme>,
    );

    await userEvent.hover(screen.getByRole("button", { name: model.title }));

    expect(screen.queryByRole("button", { name: "Pin" })).toBeNull();
  });
});
