import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useRetainedConfigOption } from "./useRetainedConfigOption";

function option(currentValue: string): SessionConfigOption {
  return {
    id: "model",
    name: "Model",
    type: "select",
    category: "model",
    currentValue,
    options: [{ value: currentValue, name: currentValue }],
  } as SessionConfigOption;
}

describe("useRetainedConfigOption", () => {
  it("returns undefined until an option is seen", () => {
    const { result } = renderHook(({ opt }) => useRetainedConfigOption(opt), {
      initialProps: { opt: undefined as SessionConfigOption | undefined },
    });
    expect(result.current).toBeUndefined();
  });

  it("returns the live option when present", () => {
    const claude = option("claude-sonnet");
    const { result } = renderHook(({ opt }) => useRetainedConfigOption(opt), {
      initialProps: { opt: claude as SessionConfigOption | undefined },
    });
    expect(result.current).toBe(claude);
  });

  it("retains the last option while it is transiently absent", () => {
    const claude = option("claude-sonnet");
    const { result, rerender } = renderHook(
      ({ opt }) => useRetainedConfigOption(opt),
      { initialProps: { opt: claude as SessionConfigOption | undefined } },
    );
    expect(result.current).toBe(claude);

    // Preview config cleared mid-switch: keep showing the previous option.
    rerender({ opt: undefined });
    expect(result.current).toBe(claude);
  });

  it("swaps to the new option once it loads, without sticking on the stale one", () => {
    const claude = option("claude-sonnet");
    const codex = option("gpt-5-codex");
    const { result, rerender } = renderHook(
      ({ opt }) => useRetainedConfigOption(opt),
      { initialProps: { opt: claude as SessionConfigOption | undefined } },
    );

    rerender({ opt: undefined }); // reload window during the switch
    expect(result.current).toBe(claude);

    rerender({ opt: codex }); // new harness config arrives
    expect(result.current).toBe(codex);

    rerender({ opt: undefined }); // a later reload retains codex, not claude
    expect(result.current).toBe(codex);
  });
});
