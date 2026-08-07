import { describe, expect, it, vi } from "vitest";
import { LinearIntegrationService } from "./linear";

function createService() {
  const urlLauncher = { launch: vi.fn().mockResolvedValue(undefined) };
  const service = new LinearIntegrationService(urlLauncher as never);
  return { service, urlLauncher };
}

describe("LinearIntegrationService.startFlow", () => {
  it("launches a linear authorize URL scoped to the project and returns success", async () => {
    const { service, urlLauncher } = createService();

    const result = await service.startFlow("us", 42);

    expect(result).toEqual({ success: true });
    const launched = urlLauncher.launch.mock.calls[0][0];
    expect(launched).toContain("/api/environments/42/integrations/authorize/");
    expect(launched).toContain("kind=linear");
  });

  it("returns a failure result when launching the browser throws", async () => {
    const { service, urlLauncher } = createService();
    urlLauncher.launch.mockRejectedValue(new Error("no browser"));

    expect(await service.startFlow("us", 42)).toEqual({
      success: false,
      error: "no browser",
    });
  });
});
