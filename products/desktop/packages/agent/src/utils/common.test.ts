import { describe, expect, it, vi } from "vitest";
import { withAbort } from "./common";

describe("withAbort", () => {
  it("resolves success when the operation settles first", async () => {
    const controller = new AbortController();

    const result = await withAbort(Promise.resolve(42), controller.signal);

    expect(result).toEqual({ result: "success", value: 42 });
  });

  it("resolves aborted when the signal fires while the operation is pending", async () => {
    const controller = new AbortController();
    let resolveOperation!: (value: string) => void;
    const operation = new Promise<string>((resolve) => {
      resolveOperation = resolve;
    });

    const raced = withAbort(operation, controller.signal);
    controller.abort();

    await expect(raced).resolves.toEqual({ result: "aborted" });
    resolveOperation("late settle is ignored");
  });

  it("resolves aborted immediately when the signal is already aborted", async () => {
    const controller = new AbortController();
    controller.abort();

    const result = await withAbort(
      new Promise<never>(() => {}),
      controller.signal,
    );

    expect(result).toEqual({ result: "aborted" });
  });

  it("rejects when the operation rejects before abort", async () => {
    const controller = new AbortController();

    await expect(
      withAbort(Promise.reject(new Error("boom")), controller.signal),
    ).rejects.toThrow("boom");
  });

  it("removes its abort listener as soon as the operation settles", async () => {
    const controller = new AbortController();
    const addSpy = vi.spyOn(controller.signal, "addEventListener");
    const removeSpy = vi.spyOn(controller.signal, "removeEventListener");
    let resolveOperation!: (value: string) => void;
    const operation = new Promise<string>((resolve) => {
      resolveOperation = resolve;
    });

    const raced = withAbort(operation, controller.signal);
    expect(addSpy).toHaveBeenCalledTimes(1);

    resolveOperation("done");
    await raced;

    expect(removeSpy).toHaveBeenCalledWith("abort", addSpy.mock.calls[0]?.[1]);
  });

  it.each([
    { label: "signal already aborted when called", abortFirst: true },
    { label: "signal aborts while pending", abortFirst: false },
  ])(
    "observes a late rejection after abort without leaving it unhandled ($label)",
    async ({ abortFirst }) => {
      const controller = new AbortController();
      if (abortFirst) {
        controller.abort();
      }
      let rejectOperation!: (error: Error) => void;
      const operation = new Promise<string>((_, reject) => {
        rejectOperation = reject;
      });
      const unhandled: unknown[] = [];
      const onUnhandled = (reason: unknown) => unhandled.push(reason);
      process.on("unhandledRejection", onUnhandled);

      try {
        const raced = withAbort(operation, controller.signal);
        if (!abortFirst) {
          controller.abort();
        }
        await expect(raced).resolves.toEqual({ result: "aborted" });

        rejectOperation(new Error("late failure"));
        await new Promise((resolve) => setImmediate(resolve));
        await new Promise((resolve) => setImmediate(resolve));

        expect(unhandled).toEqual([]);
      } finally {
        process.off("unhandledRejection", onUnhandled);
      }
    },
  );
});
