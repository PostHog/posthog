import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  PostHogAPIClient,
  SandboxCustomImagesDisabledError,
} from "./posthog-client";

function makeClient(fetch: ReturnType<typeof vi.fn>): PostHogAPIClient {
  const client = new PostHogAPIClient(
    "http://localhost:8000",
    async () => "token",
    async () => "token",
    123,
  );
  (
    client as unknown as {
      api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
    }
  ).api = { baseUrl: "http://localhost:8000", fetcher: { fetch } };
  return client;
}

describe("PostHogAPIClient sandbox custom images", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("maps a 403 on list to SandboxCustomImagesDisabledError", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      statusText: "Forbidden",
      json: async () => ({ detail: "not enabled" }),
    });
    await expect(
      makeClient(fetch).listSandboxCustomImages(),
    ).rejects.toBeInstanceOf(SandboxCustomImagesDisabledError);
  });

  it("does not map a non-403 list error to the disabled error", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Server Error",
      json: async () => ({ detail: "boom" }),
    });
    const promise = makeClient(fetch).listSandboxCustomImages();
    await expect(promise).rejects.toThrow();
    await expect(promise).rejects.not.toBeInstanceOf(
      SandboxCustomImagesDisabledError,
    );
  });

  it.each([
    ["undefined spec", undefined, {}],
    ["null spec", null, { spec_yaml: null }],
    ["string spec", "version: 1", { spec_yaml: "version: 1" }],
  ])("builds with %s body", async (_name, specYaml, expectedBody) => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "im-1" }),
    });

    await makeClient(fetch).buildSandboxCustomImage("im-1", specYaml);

    expect(fetch).toHaveBeenCalledWith(
      expect.objectContaining({
        overrides: { body: JSON.stringify(expectedBody) },
      }),
    );
  });

  it.each([
    ["name only", { name: "renamed" }],
    ["description only", { description: "updated" }],
    ["both", { name: "renamed", description: "updated" }],
  ])("patches %s via updateSandboxCustomImage", async (_name, input) => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "im-1", ...input }),
    });

    await makeClient(fetch).updateSandboxCustomImage("im-1", input);

    expect(fetch).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "patch",
        path: `/api/projects/123/sandbox_custom_images/im-1/`,
        overrides: { body: JSON.stringify(input) },
      }),
    );
  });

  it("throws the backend detail message when update fails", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      statusText: "Bad Request",
      json: async () => ({ detail: "Name cannot be blank." }),
    });

    await expect(
      makeClient(fetch).updateSandboxCustomImage("im-1", { name: "  " }),
    ).rejects.toThrow("Name cannot be blank.");
  });
});
