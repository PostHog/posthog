import { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { Task } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { findTask, WorkList } from "./work";

function fakeApi(total: number, hang = false) {
  const requests: URL[] = [];
  const api = new PostHogAPIClient(
    "https://us.posthog.com",
    async () => "token",
    async () => "token",
    undefined,
    {
      fetch: async (input) => {
        const url = new URL(input instanceof Request ? input.url : input);
        requests.push(url);
        if (url.pathname === "/api/users/@me/") {
          return Response.json({ id: 7, uuid: "u", team: { id: 2 } });
        }
        if (hang) return new Promise<Response>(() => {});
        const limit = Number(url.searchParams.get("limit"));
        const results = Array.from(
          { length: Math.min(limit, total) },
          (_, i) => ({ id: `t${i}` }),
        );
        return Response.json({ results, count: total });
      },
    },
  );
  return { api, requests };
}

describe("WorkList", () => {
  it.each([
    ["more tasks than shown", 25, 10, true],
    ["every task shown", 10, 10, false],
  ])(
    "lists my most recently active tasks when there are %s",
    async (_, total, limit, hasMore) => {
      const { api, requests } = fakeApi(total);

      const page = await new WorkList(api).listRecent(limit);

      expect(page.tasks).toHaveLength(limit);
      expect(page.hasMore).toBe(hasMore);
      const list = requests.find((url) => url.pathname.endsWith("/tasks/"));
      expect(list?.pathname).toBe("/api/projects/2/tasks/");
      expect(Object.fromEntries(list?.searchParams ?? [])).toMatchObject({
        limit: String(limit),
        ordering: "-last_activity_at",
        created_by: "7",
      });
    },
  );

  it("shares one request between overlapping refreshes", async () => {
    const { api, requests } = fakeApi(3);
    const list = new WorkList(api);

    await Promise.all([list.listRecent(10), list.listRecent(10)]);

    expect(
      requests.filter((url) => url.pathname.endsWith("/tasks/")),
    ).toHaveLength(1);
  });

  it("gives up on a request that hangs so the next refresh can try again", async () => {
    const { api } = fakeApi(3, true);
    const list = new WorkList(api, 50);

    await expect(list.listRecent(10)).rejects.toThrow("Timed out loading work");
  });
});

describe("findTask", () => {
  const task = (runId: string, title: string): Task =>
    ({ id: "t1", title, latest_run: { id: runId } }) as Task;

  it.each([
    ["a just-started run until the list catches up", "r1", "r2", "started"],
    ["the listed task once it shows the same run", "r2", "r2", "listed"],
  ])("returns %s", (_, listedRun, freshRun, expected) => {
    const found = findTask("t1", {
      listed: [task(listedRun, "listed")],
      known: new Map(),
      fresh: new Map([["t1", task(freshRun, "started")]]),
    });

    expect(found?.title).toBe(expected);
  });
});
