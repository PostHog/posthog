import { describe, expect, it, vi } from "vitest";
import { createFragmentCompiler } from "./fragmentCompiler";

describe("createFragmentCompiler", () => {
  it("batches shared sources, waits for missing output, and releases completed requests", async () => {
    vi.useFakeTimers();
    try {
      const load = vi.fn(async (refs: string[]) =>
        Object.fromEntries(refs.map((ref) => [ref, `${ref}!`])),
      );
      load.mockResolvedValueOnce({});
      const embeddedCompiler = new Function(
        `return (${createFragmentCompiler.toString()})`,
      )() as typeof createFragmentCompiler;
      const compile = embeddedCompiler(load);
      const first = compile("0");
      expect(compile("0")).toBe(first);
      const refs = Array.from({ length: 514 }, (_, i) => String(i));
      const result = Promise.all(refs.map(compile));
      await vi.runAllTimersAsync();
      expect(await result).toEqual(refs.map((ref) => `${ref}!`));
      expect(load.mock.calls.map(([batch]) => batch.length)).toEqual([
        256, 256, 256, 2,
      ]);
      await expect(compile("0")).resolves.toBe("0!");
      load.mockRejectedValueOnce(new Error("Network error"));
      await expect(compile("retry")).rejects.toThrow("Network error");
      await expect(compile("retry")).resolves.toBe("retry!");
    } finally {
      vi.useRealTimers();
    }
  });
});
