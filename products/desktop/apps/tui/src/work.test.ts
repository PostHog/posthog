import { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import { WorkList } from "./work";

function fakeApi(total: number) {
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
});
