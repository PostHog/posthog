import { describe, expect, it } from "vitest";
import { enabledLocalTools } from "../index";
import { SPEAK_TOOL_NAME, speakSchema, speakTool } from "./speak";

describe("speak tool", () => {
  it.each([
    { name: "desktop", environment: "local" as const },
    { name: "cloud", environment: "cloud" as const },
  ])("is exposed with narration on ($name)", ({ environment }) => {
    const tools = enabledLocalTools(
      { cwd: "/repo" },
      { environment, spokenNarration: true },
    );
    expect(tools.some((t) => t.name === SPEAK_TOOL_NAME)).toBe(true);
  });

  it.each([
    {
      name: "narration off",
      meta: { environment: "local" as const, spokenNarration: false },
    },
    { name: "narration unset", meta: { environment: "local" as const } },
    { name: "no gate meta", meta: undefined },
  ])("is hidden with $name", ({ meta }) => {
    const tools = enabledLocalTools({ cwd: "/repo" }, meta);
    expect(tools.some((t) => t.name === SPEAK_TOOL_NAME)).toBe(false);
  });

  it("stays visible without ToolSearch (alwaysLoad)", () => {
    expect(speakTool.alwaysLoad).toBe(true);
  });

  it("validates a well-formed line", () => {
    expect(
      speakSchema.text.safeParse("[excited] tests are green!").success,
    ).toBe(true);
  });

  it("rejects empty text", () => {
    expect(speakSchema.text.safeParse("").success).toBe(false);
  });

  it.each(["needs_input", "done", "progress"])("accepts kind %s", (kind) => {
    expect(speakSchema.kind.safeParse(kind).success).toBe(true);
  });

  it("rejects an unknown kind", () => {
    expect(speakSchema.kind.safeParse("chatter").success).toBe(false);
  });

  it("handler acknowledges without side effects", async () => {
    const result = await speakTool.handler(
      { cwd: "/repo" },
      { text: "hello", kind: "done" },
    );
    expect(result.isError).toBeUndefined();
    expect(result.content[0]).toMatchObject({ type: "text" });
  });
});
