import { beforeEach, describe, expect, it, vi } from "vitest";

const existsSyncMock = vi.hoisted(() => vi.fn());
vi.mock("node:fs", async (importOriginal) => ({
  ...(await importOriginal<typeof import("node:fs")>()),
  existsSync: existsSyncMock,
}));

const resolveMock = vi.hoisted(() => vi.fn());
vi.mock("node:module", async (importOriginal) => ({
  ...(await importOriginal<typeof import("node:module")>()),
  createRequire: () => ({ resolve: resolveMock }),
}));

const { nativeCodexBinaryPath } = await import("./binary-path");

describe("nativeCodexBinaryPath", () => {
  beforeEach(() => {
    existsSyncMock.mockReset();
    resolveMock.mockReset();
  });

  it("returns the sibling codex binary bundled next to codex-acp when present", () => {
    existsSyncMock.mockReturnValue(true);
    expect(nativeCodexBinaryPath("/bundle/codex-acp/codex-acp")).toBe(
      "/bundle/codex-acp/codex",
    );
  });

  it("falls back to the @openai/codex vendored binary when no sibling is bundled", () => {
    resolveMock.mockReturnValue("/nm/@openai/codex-plat/package.json");
    existsSyncMock.mockImplementation((p: string) => p.includes("/vendor/"));
    const got = nativeCodexBinaryPath(undefined);
    expect(got).toContain("@openai/codex-plat");
    expect(got).toContain("/vendor/");
    expect(got?.endsWith("/bin/codex")).toBe(true);
  });

  it("returns undefined when neither the sibling nor the @openai/codex dep is present", () => {
    existsSyncMock.mockReturnValue(false);
    resolveMock.mockImplementation(() => {
      throw new Error("Cannot find module '@openai/codex-plat/package.json'");
    });
    expect(
      nativeCodexBinaryPath("/bundle/codex-acp/codex-acp"),
    ).toBeUndefined();
    expect(nativeCodexBinaryPath(undefined)).toBeUndefined();
  });
});
