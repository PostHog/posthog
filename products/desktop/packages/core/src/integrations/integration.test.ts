import { describe, expect, it, vi } from "vitest";
import { IntegrationService } from "./integration";

function createService() {
  const urlLauncher = { launch: vi.fn().mockResolvedValue(undefined) };
  const service = new IntegrationService(urlLauncher as never);
  return { service, urlLauncher };
}

describe("IntegrationService.startFlow", () => {
  it("launches an authorize URL for the given kind scoped to the project", async () => {
    const { service, urlLauncher } = createService();

    const result = await service.startFlow("intercom", "us", 42);

    expect(result).toEqual({ success: true });
    const launched = urlLauncher.launch.mock.calls[0][0];
    expect(launched).toContain("/api/environments/42/integrations/authorize/");
    expect(launched).toContain("kind=intercom");
  });

  it("url-encodes the kind", async () => {
    const { service, urlLauncher } = createService();

    await service.startFlow("rapid7_insightvm", "eu", 7);

    expect(urlLauncher.launch.mock.calls[0][0]).toContain(
      "kind=rapid7_insightvm",
    );
  });

  it("returns a failure result when launching the browser throws", async () => {
    const { service, urlLauncher } = createService();
    urlLauncher.launch.mockRejectedValue(new Error("no browser"));

    expect(await service.startFlow("hubspot", "us", 42)).toEqual({
      success: false,
      error: "no browser",
    });
  });
});
