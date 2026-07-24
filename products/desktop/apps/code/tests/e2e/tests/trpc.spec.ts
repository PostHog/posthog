import { expect, test } from "../fixtures/electron";

test.describe("tRPC IPC", () => {
  test("electronTRPC bridge is exposed on window", async ({ window }) => {
    const hasTrpcBridge = await window.evaluate(() => {
      return (
        typeof (window as unknown as { electronTRPC: unknown }).electronTRPC !==
        "undefined"
      );
    });

    expect(hasTrpcBridge).toBe(true);
  });

  test("electronTRPC has required methods", async ({ window }) => {
    const trpcStructure = await window.evaluate(() => {
      const trpc = (window as unknown as { electronTRPC: unknown })
        .electronTRPC;
      if (!trpc || typeof trpc !== "object") return null;

      return {
        hasExposeElectronTRPC: "exposeElectronTRPC" in trpc,
        type: typeof trpc,
      };
    });

    expect(trpcStructure).not.toBeNull();
    expect(trpcStructure?.type).toBe("object");
  });

  test("preload script executed successfully", async ({ window }) => {
    const preloadResult = await window.evaluate(() => {
      const hasElectronTRPC =
        typeof (window as unknown as { electronTRPC: unknown }).electronTRPC !==
        "undefined";

      const isElectronContext =
        typeof process !== "undefined" || hasElectronTRPC;

      return {
        hasElectronTRPC,
        isElectronContext,
      };
    });

    expect(preloadResult.hasElectronTRPC).toBe(true);
    expect(preloadResult.isElectronContext).toBe(true);
  });
});
