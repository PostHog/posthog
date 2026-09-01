import { describe, expect, it, vi } from "vitest";
import { type DocSchemas, DocsApiError, saveDocSteps } from "./docs";
import { ApiRequestError } from "./fetcher";
import { createApiClient, type Fetcher } from "./generated";

const BASE_URL = "https://app.posthog.com";
const PROJECT_ID = "1";
const DOC_ID = "doc-abc";

const SAVE: DocSchemas.CollabSave = {
  client_id: "client-1",
  steps: [{ stepType: "replace", from: 0, to: 0 }],
  version: 3,
  content: { type: "doc", content: [] },
};

// Mirrors the real fetcher, which throws ApiRequestError on any non-2xx rather
// than returning the response. A fake that resolves instead would hide the very
// bug these cases exist for.
function fakeFetcher(data: unknown, status: number): Fetcher {
  if (status >= 400) {
    return {
      fetch: vi
        .fn()
        .mockRejectedValue(
          new ApiRequestError(status, JSON.stringify(data), data),
        ),
    };
  }
  return {
    fetch: vi.fn().mockResolvedValue({
      ok: true,
      status,
      clone: () => ({ json: () => Promise.resolve(data) }),
      headers: {
        get: (key: string) =>
          key === "content-type" ? "application/json" : null,
      },
      json: () => Promise.resolve(data),
    }),
  };
}

describe("docs client", () => {
  // Two people typing at once is the normal case, not an error: a rejected batch
  // has to come back as data so the editor can rebase and send again. If this
  // ever throws instead, live editing breaks the moment a second person types.
  it.each([
    {
      name: "conflict carries the missed steps",
      status: 409,
      body: {
        code: "conflict",
        version: 5,
        steps: [{ stepType: "replace", from: 1, to: 1 }],
        client_ids: ["client-2"],
      },
      expected: "conflict",
    },
    {
      name: "stale asks for a reload",
      status: 410,
      body: { code: "stale", version: 9 },
      expected: "stale",
    },
  ])("$name", async ({ status, body, expected }) => {
    const client = createApiClient(fakeFetcher(body, status), BASE_URL);

    const result = await saveDocSteps(client, PROJECT_ID, DOC_ID, SAVE);

    expect(result.status).toBe(expected);
    if (result.status === "accepted") throw new Error("expected a rejection");
    expect(result.conflict.version).toBe(body.version);
  });

  it("still throws on a real failure", async () => {
    const client = createApiClient(
      fakeFetcher({ detail: "boom" }, 500),
      BASE_URL,
    );

    await expect(
      saveDocSteps(client, PROJECT_ID, DOC_ID, SAVE),
    ).rejects.toBeInstanceOf(DocsApiError);
  });
});
