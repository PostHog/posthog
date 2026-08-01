import { ServiceProvider } from "@posthog/di/react";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { Container } from "inversify";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "../../../feature-flags/identifiers";
import { UserMessage } from "./UserMessage";

function renderWithFlags(node: ReactNode, bluebirdEnabled: boolean) {
  const flags: FeatureFlags = {
    isEnabled: () => bluebirdEnabled,
    onFlagsLoaded: () => () => {},
  };
  const container = new Container();
  container.bind(FEATURE_FLAGS).toConstantValue(flags);
  return render(
    <ServiceProvider container={container}>
      <Theme>{node}</Theme>
    </ServiceProvider>,
  );
}

const PROMPT_WITH_CONTEXT =
  'do the thing\n<channel_context channel="billing">\n# Billing\n</channel_context>';

const PROMPT_WITH_CANVAS_INSTRUCTIONS =
  "add a retention chart\n\n<canvas_generation_instructions>\nauthoring contract\n</canvas_generation_instructions>";

describe("UserMessage", () => {
  // useFeatureFlag falls back to import.meta.env.DEV, which is true under
  // vitest. Pin DEV off in the flag-gating cases so they exercise the flag
  // itself, not the dev default.
  afterEach(() => {
    vi.unstubAllEnvs();
  });
  it("renders attachment chips for cloud prompts", () => {
    renderWithFlags(
      <UserMessage
        content="read this file"
        attachments={[
          { id: "attachment://test.txt", label: "test.txt" },
          { id: "attachment://notes.md", label: "notes.md" },
        ]}
      />,
      true,
    );

    expect(screen.getByText("read this file")).toBeInTheDocument();
    expect(screen.getByText("test.txt")).toBeInTheDocument();
    expect(screen.getByText("notes.md")).toBeInTheDocument();
  });

  it("shows the channel CONTEXT.md tag when project-bluebird is enabled", () => {
    vi.stubEnv("DEV", false);
    renderWithFlags(
      <UserMessage content={PROMPT_WITH_CONTEXT} taskId="task-1" />,
      true,
    );

    expect(screen.getByText("do the thing")).toBeInTheDocument();
    expect(screen.getByText("#billing CONTEXT.md")).toBeInTheDocument();
  });

  it("hides the tag but still strips the block when project-bluebird is off", () => {
    vi.stubEnv("DEV", false);
    renderWithFlags(
      <UserMessage content={PROMPT_WITH_CONTEXT} taskId="task-1" />,
      false,
    );

    // Prompt still renders, the channel-context tag does not.
    expect(screen.getByText("do the thing")).toBeInTheDocument();
    expect(screen.queryByText("#billing CONTEXT.md")).not.toBeInTheDocument();
    // The raw <channel_context> XML must never leak to flag-off viewers.
    expect(screen.queryByText(/channel_context/)).not.toBeInTheDocument();
  });

  it("shows the canvas-instructions tag when project-bluebird is enabled", () => {
    vi.stubEnv("DEV", false);
    renderWithFlags(
      <UserMessage content={PROMPT_WITH_CANVAS_INSTRUCTIONS} taskId="task-1" />,
      true,
    );

    expect(screen.getByText("add a retention chart")).toBeInTheDocument();
    expect(screen.getByText("Canvas instructions")).toBeInTheDocument();
    // The contract body is collapsed into the tag, not rendered inline.
    expect(screen.queryByText("authoring contract")).not.toBeInTheDocument();
  });

  it("hides the canvas-instructions tag but still strips the block when off", () => {
    vi.stubEnv("DEV", false);
    renderWithFlags(
      <UserMessage content={PROMPT_WITH_CANVAS_INSTRUCTIONS} taskId="task-1" />,
      false,
    );

    expect(screen.getByText("add a retention chart")).toBeInTheDocument();
    expect(screen.queryByText("Canvas instructions")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/canvas_generation_instructions/),
    ).not.toBeInTheDocument();
  });
});
