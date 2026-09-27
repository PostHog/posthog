import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  app: { commandLine: { getSwitchValue: () => "" } },
  session: { fromPartition: vi.fn() },
  webContents: { fromId: vi.fn() },
}));

import { authorizeTaskPreview } from "./electron-task-preview";

describe("authorizeTaskPreview", () => {
  it("moves the sandbox token into an http-only cookie", async () => {
    const cookies = { set: vi.fn(async () => undefined) };

    await expect(
      authorizeTaskPreview(
        "https://abc-123.modal.host/?_modal_connect_token=secret",
        cookies,
      ),
    ).resolves.toBe("https://abc-123.modal.host/");
    expect(cookies.set).toHaveBeenCalledWith({
      url: "https://abc-123.modal.host",
      name: "_modal_connect_token",
      value: "secret",
      path: "/",
      secure: true,
      httpOnly: true,
      sameSite: "strict",
    });

    await expect(
      authorizeTaskPreview(
        "https://evil.example.com/?_modal_connect_token=secret",
        cookies,
      ),
    ).resolves.toBeNull();
    await expect(
      authorizeTaskPreview(
        "http://localhost:3000/?_modal_connect_token=secret",
        cookies,
      ),
    ).resolves.toBeNull();
    expect(cookies.set).toHaveBeenCalledOnce();
  });
});
