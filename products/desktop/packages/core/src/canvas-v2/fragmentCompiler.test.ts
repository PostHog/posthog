import { describe, expect, it, vi } from "vitest";
import { createFragmentCompiler } from "./fragmentCompiler";

describe("createFragmentCompiler", () => {
  it("reuses compiled source within a fixed budget and retries failed builds", () => {
    const transform = vi.fn((source: string) => `${source}!`);
    const compile = createFragmentCompiler(transform, 6);
    expect(compile("a")).toBe("a!");
    expect(compile("b")).toBe("b!");
    expect(compile("a")).toBe("a!");
    expect(transform).toHaveBeenCalledTimes(2);
    compile("c");
    compile("b");
    expect(transform).toHaveBeenCalledTimes(4);
    compile("large");
    compile("large");
    expect(transform).toHaveBeenCalledTimes(6);
    transform.mockImplementationOnce(() => {
      throw new Error("Invalid source");
    });
    expect(() => compile("x")).toThrow("Invalid source");
    expect(compile("x")).toBe("x!");
    expect(transform).toHaveBeenCalledTimes(8);
  });
});
