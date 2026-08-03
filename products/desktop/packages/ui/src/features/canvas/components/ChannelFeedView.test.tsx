import type { Task } from "@posthog/shared/domain-types";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({
  Link: ({
    children,
    onClick,
  }: {
    children: React.ReactNode;
    onClick?: () => void;
  }) => (
    <a
      href="/task"
      onClick={(event) => {
        event.preventDefault();
        onClick?.();
      }}
    >
      {children}
    </a>
  ),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTaskData", () => ({
  useChannelTaskData: () => undefined,
}));
vi.mock("@posthog/ui/features/sidebar/useTaskPrStatus", () => ({
  useTaskPrStatus: () => ({ prState: null }),
}));
vi.mock("@posthog/ui/features/browser-tabs/TaskTabIcon", () => ({
  TaskTabIcon: () => <span />,
}));

import { TaskCard, TaskFeedRow } from "./ChannelFeedView";

const task = {
  id: "task-1",
  task_number: 1,
  slug: "task-1",
  title: "Investigate signup drop-off",
  description: "A long prompt that needs to be expanded in the channel feed",
  created_at: "2026-07-17T12:00:00.000Z",
  updated_at: "2026-07-17T12:00:00.000Z",
  origin_product: "user_created",
  created_by: {
    id: 1,
    uuid: "user-1",
    email: "person@example.com",
    first_name: "A",
    last_name: "Person",
  },
} satisfies Task;

afterEach(() => {
  vi.restoreAllMocks();
});

// ExpandablePrompt measures how the prompt wraps to decide where to cut and
// whether to show "more". jsdom does no layout, so simulate a 21px line height
// and a scrollHeight that grows with text length (≈20 chars/line).
function mockLayout(charsPerLine: number) {
  const realGetComputedStyle = window.getComputedStyle;
  vi.spyOn(window, "getComputedStyle").mockImplementation((el, ...rest) => {
    const style = realGetComputedStyle(el, ...rest);
    return new Proxy(style, {
      get(target, prop) {
        if (prop === "lineHeight") return "21px";
        const value = Reflect.get(target, prop);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });
  });
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(
    function (this: HTMLElement) {
      return Math.ceil((this.textContent ?? "").length / charsPerLine) * 21;
    },
  );
}

describe("TaskFeedRow", () => {
  it("reports when its task is opened", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <Theme>
        <TaskCard task={task} channelId="channel-1" onOpen={onOpen} />
      </Theme>,
    );

    await user.click(screen.getByText(task.title));

    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("expands a truncated prompt", async () => {
    mockLayout(20);
    const user = userEvent.setup();
    const { container } = render(
      <Theme>
        <TaskFeedRow task={task} />
      </Theme>,
    );

    const prompt = container.querySelector(
      "[data-slot=thread-item-body]",
    ) as HTMLElement;
    // The visible text is the non-measure child (the measure copy is aria-hidden).
    const visible = Array.from(prompt.children).find(
      (c) => !c.hasAttribute("aria-hidden"),
    ) as HTMLElement;
    const more = screen.getByRole("button", { name: "more" });
    // The toggle sits inside the visible prompt text, inline after the ellipsis —
    // not on a separate line below.
    expect(visible).toContainElement(more);
    expect(visible.textContent).toContain("…");
    expect(visible.textContent).not.toContain(task.description);

    await user.click(more);

    expect(visible.textContent).toContain(task.description);
    expect(screen.getByRole("button", { name: "less" })).toBeInTheDocument();
  });

  it("renders no toggle when the prompt fits", () => {
    mockLayout(1000);
    render(
      <Theme>
        <TaskFeedRow task={task} />
      </Theme>,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
