import type { Task } from "@posthog/shared/domain-types";
import type { AgentSession } from "@posthog/ui/features/sessions/sessionStore";
import { describe, expect, it } from "vitest";
import { resolveCloudPrUrl, resolveCloudPrUrls } from "./cloudPrUrl";

function makeTask(prUrl?: unknown): Task {
  return {
    id: "task-1",
    latest_run: { output: { pr_url: prUrl } },
  } as unknown as Task;
}

function makeSession(prUrl?: unknown): AgentSession {
  return { cloudOutput: { pr_url: prUrl } } as unknown as AgentSession;
}

describe("resolveCloudPrUrl", () => {
  it("returns null when both task and session are undefined", () => {
    expect(resolveCloudPrUrl(undefined, undefined)).toBeNull();
  });

  it("returns task PR URL when available", () => {
    const task = makeTask("https://github.com/org/repo/pull/1");
    expect(resolveCloudPrUrl(task, undefined)).toBe(
      "https://github.com/org/repo/pull/1",
    );
  });

  it("returns session PR URL when task has none", () => {
    const task = makeTask(undefined);
    const session = makeSession("https://github.com/org/repo/pull/2");
    expect(resolveCloudPrUrl(task, session)).toBe(
      "https://github.com/org/repo/pull/2",
    );
  });

  it("prefers task PR URL over session", () => {
    const task = makeTask("https://github.com/org/repo/pull/1");
    const session = makeSession("https://github.com/org/repo/pull/2");
    expect(resolveCloudPrUrl(task, session)).toBe(
      "https://github.com/org/repo/pull/1",
    );
  });

  it("ignores non-string pr_url values", () => {
    expect(resolveCloudPrUrl(makeTask(123), makeSession(true))).toBeNull();
    expect(resolveCloudPrUrl(makeTask(null), makeSession(null))).toBeNull();
  });

  it("ignores empty string pr_url", () => {
    expect(resolveCloudPrUrl(makeTask(""), makeSession(""))).toBeNull();
  });

  it("falls back to session when task pr_url is empty", () => {
    const session = makeSession("https://github.com/org/repo/pull/3");
    expect(resolveCloudPrUrl(makeTask(""), session)).toBe(
      "https://github.com/org/repo/pull/3",
    );
  });

  it("returns the first entry of pr_urls as the primary", () => {
    const task = {
      id: "task-1",
      latest_run: {
        output: {
          pr_url: "https://github.com/org/repo/pull/1",
          pr_urls: [
            "https://github.com/org/repo/pull/1",
            "https://github.com/org/repo/pull/2",
          ],
        },
      },
    } as unknown as Task;
    expect(resolveCloudPrUrl(task, undefined)).toBe(
      "https://github.com/org/repo/pull/1",
    );
  });
});

describe("resolveCloudPrUrls", () => {
  it("returns an empty list when both sources are undefined", () => {
    expect(resolveCloudPrUrls(undefined, undefined)).toEqual([]);
  });

  it("unions task and session URLs with task order winning", () => {
    const task = {
      id: "task-1",
      latest_run: {
        output: {
          pr_url: "https://github.com/org/repo/pull/1",
          pr_urls: [
            "https://github.com/org/repo/pull/1",
            "https://github.com/org/repo/pull/2",
          ],
        },
      },
    } as unknown as Task;
    const session = {
      cloudOutput: { pr_url: "https://github.com/org/repo/pull/3" },
    } as unknown as AgentSession;
    expect(resolveCloudPrUrls(task, session)).toEqual([
      "https://github.com/org/repo/pull/1",
      "https://github.com/org/repo/pull/2",
      "https://github.com/org/repo/pull/3",
    ]);
  });

  it("appends a diverging legacy pr_url after the listed ones", () => {
    const task = {
      id: "task-1",
      latest_run: {
        output: {
          pr_url: "https://github.com/org/repo/pull/9",
          pr_urls: ["https://github.com/org/repo/pull/1"],
        },
      },
    } as unknown as Task;
    expect(resolveCloudPrUrls(task, undefined)).toEqual([
      "https://github.com/org/repo/pull/1",
      "https://github.com/org/repo/pull/9",
    ]);
  });
});
