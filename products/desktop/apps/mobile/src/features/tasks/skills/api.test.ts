import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockFetch } = vi.hoisted(() => ({
  mockFetch: vi.fn(),
}));

vi.mock("expo/fetch", () => ({
  fetch: mockFetch,
}));

vi.mock("@/lib/api", () => ({
  getBaseUrl: () => "https://app.posthog.test",
  getProjectId: () => 42,
  authedFetch: (url: string, init?: RequestInit) =>
    mockFetch(url, {
      ...init,
      headers: {
        Authorization: "Bearer token",
        "Content-Type": "application/json",
        ...((init?.headers as Record<string, string> | undefined) ?? {}),
      },
    }),
}));

import { getSkillStoreSkill, getSkillStoreSkills } from "./api";

describe("skill store api", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("parses paginated skill-list responses", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          results: [
            {
              name: "shared-daily-brief",
              description: "Shared morning briefing starter",
            },
          ],
        }),
        { status: 200 },
      ),
    );

    const skills = await getSkillStoreSkills();

    expect(skills).toEqual([
      {
        name: "shared-daily-brief",
        description: "Shared morning briefing starter",
      },
    ]);
    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.test/api/environments/42/llm_skills/",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer token",
        }),
      }),
    );
  });

  it("encodes skill names for detail requests and returns the full body", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          name: "shared/brief today",
          description: "Shared briefing",
          body: "Summarize what matters this morning.",
        }),
        { status: 200 },
      ),
    );

    const skill = await getSkillStoreSkill("shared/brief today");

    expect(skill).toMatchObject({
      name: "shared/brief today",
      body: "Summarize what matters this morning.",
    });
    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.test/api/environments/42/llm_skills/name/shared%2Fbrief%20today/",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer token",
        }),
      }),
    );
  });
});
