import type { AutoresearchRun } from "@posthog/core/autoresearch/schemas";
import type { AcpMessage } from "@posthog/shared";
import { Theme } from "@radix-ui/themes";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AutoresearchObservability } from "./AutoresearchObservability";

function updateEvent(ts: number, update: Record<string, unknown>): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: { update },
    },
  } as AcpMessage;
}

function makeRun(overrides: Partial<AutoresearchRun> = {}): AutoresearchRun {
  return {
    id: "run-1",
    config: {
      taskId: "task-1",
      direction: "minimize",
      targetValue: null,
      maxIterations: 10,
      implementModel: null,
      measureModel: null,
      implementEffort: null,
      measureEffort: null,
      instructions: "Reduce memory usage.",
    },
    status: "running",
    metricName: "memory",
    metricUnit: "MB",
    phase: null,
    originalModel: null,
    originalEffort: null,
    researchFindings: [
      {
        index: 1,
        summary: "Mapped the hot path",
        finding: "Serialization dominates the current measurement.",
        nextStep: "Inspect the serializer",
        area: "workspace server",
        at: 1_500,
      },
    ],
    iterations: [],
    startedAt: 1_000,
    endedAt: null,
    endReason: null,
    interruptedReason: null,
    lastError: null,
    ...overrides,
  };
}

describe("AutoresearchObservability", () => {
  it("renders timeline-shaped skeletons before the first activity", () => {
    render(
      <Theme>
        <AutoresearchObservability run={makeRun()} events={[]} />
      </Theme>,
    );

    const loading = screen.getByRole("status", {
      name: "Loading live timeline",
    });
    expect(within(loading).getAllByRole("listitem")).toHaveLength(3);
    expect(loading.querySelectorAll('[data-slot="skeleton"]')).toHaveLength(10);
  });

  it("renders current findings and a reconciled newest-first timeline", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        toolCallId: "search-1",
        title: "Search serializers",
        kind: "search",
        status: "in_progress",
      }),
      updateEvent(3_000, {
        sessionUpdate: "tool_call_update",
        toolCallId: "search-1",
        status: "completed",
      }),
      updateEvent(5_000, {
        sessionUpdate: "tool_call",
        toolCallId: "edit-1",
        title: "Edit serializer",
        kind: "edit",
        status: "in_progress",
      }),
    ];

    render(
      <Theme>
        <AutoresearchObservability run={makeRun()} events={events} />
      </Theme>,
    );

    expect(screen.getByText("Current findings")).toBeVisible();
    expect(screen.getByText("Mapped the hot path")).toBeVisible();
    const timeline = screen.getByText("Edit serializer").closest("ol");
    const collapsible = timeline?.closest('[data-slot="collapsible"]');
    expect(collapsible).toHaveClass(
      "bg-transparent",
      "hover:bg-transparent",
      "data-open:bg-transparent",
    );
    expect(screen.getByRole("button", { name: "Live timeline" })).toHaveClass(
      "aria-expanded:bg-transparent",
    );
    expect(timeline?.parentElement).toHaveClass("pt-3");
    const items = within(timeline as HTMLElement).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Edit serializer");
    expect(items[0]).toHaveTextContent("Now");
    expect(items[0].querySelector("time")).toHaveAttribute(
      "datetime",
      new Date(5_000).toISOString(),
    );
    expect(items[1]).toHaveTextContent("Search serializers");
    expect(items[1]).not.toHaveTextContent("Now");
  });

  it("toggles the live timeline", async () => {
    const user = userEvent.setup();
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        title: "Search serializers",
        kind: "search",
        status: "completed",
      }),
    ];

    render(
      <Theme>
        <AutoresearchObservability run={makeRun()} events={events} />
      </Theme>,
    );

    const trigger = screen.getByRole("button", { name: "Live timeline" });
    expect(screen.getByText("Search serializers")).toBeVisible();

    await user.click(trigger);
    expect(screen.queryByText("Search serializers")).not.toBeInTheDocument();

    await user.click(trigger);
    expect(screen.getByText("Search serializers")).toBeVisible();
  });

  it("labels only the newest live command as now", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        title: "Start dev server",
        kind: "execute",
        status: "in_progress",
      }),
      updateEvent(4_000, {
        sessionUpdate: "tool_call",
        title: "Run benchmark",
        kind: "execute",
        status: "in_progress",
      }),
    ];

    render(
      <Theme>
        <AutoresearchObservability run={makeRun()} events={events} />
      </Theme>,
    );

    const timeline = screen.getByText("Run benchmark").closest("ol");
    const items = within(timeline as HTMLElement).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Run benchmark");
    expect(items[0]).toHaveTextContent("Now");
    expect(items[0].querySelector("[data-timeline-details]")).toHaveTextContent(
      "Now",
    );
    expect(within(items[0]).getByText("Now").parentElement).toHaveClass(
      "ml-auto",
    );
    expect(items[0]).not.toHaveClass("bg-blue-2/50");
    expect(within(items[0]).getByText("Now")).not.toHaveClass(
      "motion-safe:animate-pulse",
    );
    expect(items[1]).toHaveTextContent("Start dev server");
    expect(items[1]).toHaveTextContent("Background");
    expect(within(items[1]).getByText("Background")).toHaveClass(
      "text-gray-10",
    );
    expect(screen.getAllByText("Now")).toHaveLength(1);
  });

  it("renders commands as single-line code tooltip triggers", () => {
    const command =
      "/bin/zsh -lc 'pnpm bench:memory -- --label autoresearch-baseline'";
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        title: command,
        kind: "execute",
        status: "in_progress",
      }),
    ];

    render(
      <Theme>
        <AutoresearchObservability run={makeRun()} events={events} />
      </Theme>,
    );

    const trigger = screen.getByText(command);
    expect(trigger.tagName).toBe("CODE");
    expect(trigger.parentElement).toHaveClass(
      "w-full",
      "max-w-full",
      "truncate",
      "font-mono",
      "bg-gray-3",
    );
    expect(trigger.parentElement).toHaveAttribute("type", "button");
    expect(
      trigger.closest("li")?.querySelector("[data-activity-icon]"),
    ).toHaveClass("h-5", "w-3.5", "items-center", "justify-center");
    const commandColumn = trigger
      .closest("li")
      ?.querySelector("[data-timeline-command-column]");
    expect(commandColumn).toContainElement(trigger);
    expect(commandColumn?.querySelector(".text-\\[11px\\]")).toBeTruthy();
    const timelineItem = trigger.closest("li");
    expect(timelineItem).toHaveClass(
      "grid",
      "w-full",
      "min-w-0",
      "grid-cols-[auto_minmax(0,1fr)]",
    );
    expect(timelineItem?.parentElement).not.toHaveClass("overflow-hidden");
  });

  it("sorts observed time from longest to shortest", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        title: "Search serializers",
        kind: "search",
        status: "completed",
      }),
      updateEvent(7_000, {
        sessionUpdate: "tool_call",
        title: "Edit serializer",
        kind: "edit",
        status: "completed",
      }),
    ];

    render(
      <Theme>
        <AutoresearchObservability
          run={makeRun({ status: "completed", endedAt: 9_000 })}
          events={events}
        />
      </Theme>,
    );

    const observedTime = screen.getByText("Observed time").closest("section");
    expect(observedTime).not.toBeNull();
    const rows = observedTime?.querySelectorAll("[data-observed-kind]");
    expect(
      Array.from(rows ?? []).map((row) =>
        row.getAttribute("data-observed-kind"),
      ),
    ).toEqual([
      "research",
      "implementation",
      "reasoning",
      "measurement",
      "execution",
    ]);
  });

  it("freezes observed time at the pause timestamp", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        title: "Run benchmark",
        kind: "execute",
        status: "in_progress",
      }),
    ];

    const { container } = render(
      <Theme>
        <AutoresearchObservability
          run={makeRun({ status: "paused", pausedAt: 11_000 })}
          events={events}
        />
      </Theme>,
    );

    expect(
      container.querySelector('[data-observed-kind="measurement"]'),
    ).toHaveTextContent("9s");
    expect(screen.queryByText("Now")).not.toBeInTheDocument();
  });
});
