import type { SlashCommand } from "@anthropic-ai/claude-agent-sdk";
import { describe, expect, it } from "vitest";
import { getAvailableSlashCommands } from "./commands";

function sdkCommand(name: string, description = ""): SlashCommand {
  return { name, description, argumentHint: null } as unknown as SlashCommand;
}

describe("getAvailableSlashCommands", () => {
  it("filters unsupported commands", () => {
    const available = getAvailableSlashCommands([
      sdkCommand("compact"),
      sdkCommand("context"),
      sdkCommand("cost"),
      sdkCommand("login"),
    ]);
    const names = available.map((c) => c.name);
    expect(names).toContain("compact");
    expect(names).not.toContain("context");
    expect(names).not.toContain("cost");
    expect(names).not.toContain("login");
  });

  it("passes the SDK's /clear entry through", () => {
    const available = getAvailableSlashCommands([
      sdkCommand("clear", "Clear conversation history"),
    ]);
    const clear = available.filter((c) => c.name === "clear");
    expect(clear).toHaveLength(1);
    expect(clear[0].description).toBe("Clear conversation history");
  });

  it("injects /clear when the SDK does not advertise it", () => {
    const available = getAvailableSlashCommands([sdkCommand("compact")]);
    const clear = available.find((c) => c.name === "clear");
    expect(clear).toBeDefined();
    expect(clear?.description).toMatch(/clear conversation history/i);
  });

  it("renames MCP commands to the mcp: prefix", () => {
    const available = getAvailableSlashCommands([
      sdkCommand("linear (MCP)", "Linear tools"),
    ]);
    expect(available.map((c) => c.name)).toContain("mcp:linear");
  });
});
