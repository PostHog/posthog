import { describe, expect, it } from "vitest";
import {
  CLOUD_PROMPT_PREFIX,
  deserializeCloudPrompt,
  promptBlocksToText,
  serializeCloudPrompt,
} from "./cloud-prompt";

describe("cloud-prompt", () => {
  describe("serializeCloudPrompt", () => {
    it("returns plain text for a single text block", () => {
      const result = serializeCloudPrompt([
        { type: "text", text: "  hello world  " },
      ]);
      expect(result).toBe("hello world");
      expect(result).not.toContain(CLOUD_PROMPT_PREFIX);
    });

    it("returns prefixed JSON for multi-block content", () => {
      const blocks = [
        { type: "text" as const, text: "read this" },
        {
          type: "resource" as const,
          resource: {
            uri: "attachment://test.txt",
            text: "file contents",
            mimeType: "text/plain",
          },
        },
      ];
      const result = serializeCloudPrompt(blocks);
      expect(result).toMatch(
        new RegExp(
          `^${CLOUD_PROMPT_PREFIX.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
        ),
      );
      const payload = JSON.parse(result.slice(CLOUD_PROMPT_PREFIX.length));
      expect(payload.blocks).toEqual(blocks);
    });
  });

  describe("deserializeCloudPrompt", () => {
    it("round-trips with serializeCloudPrompt (text-only)", () => {
      const original = [{ type: "text" as const, text: "hello" }];
      const serialized = serializeCloudPrompt(original);
      const deserialized = deserializeCloudPrompt(serialized);
      expect(deserialized).toEqual(original);
    });

    it("round-trips with serializeCloudPrompt (multi-block)", () => {
      const original = [
        { type: "text" as const, text: "read this" },
        {
          type: "resource" as const,
          resource: {
            uri: "attachment://test.txt",
            text: "contents",
            mimeType: "text/plain",
          },
        },
      ];
      const serialized = serializeCloudPrompt(original);
      const deserialized = deserializeCloudPrompt(serialized);
      expect(deserialized).toEqual(original);
    });

    it("wraps plain string (no prefix) as a text block", () => {
      const result = deserializeCloudPrompt("just a plain message");
      expect(result).toEqual([{ type: "text", text: "just a plain message" }]);
    });

    it("returns empty array for empty string", () => {
      expect(deserializeCloudPrompt("")).toEqual([]);
      expect(deserializeCloudPrompt("   ")).toEqual([]);
    });

    it("falls back to text block for malformed JSON after prefix", () => {
      const malformed = `${CLOUD_PROMPT_PREFIX}{not valid json`;
      const result = deserializeCloudPrompt(malformed);
      expect(result).toEqual([{ type: "text", text: malformed }]);
    });

    it("falls back to text block for empty blocks array", () => {
      const payload = `${CLOUD_PROMPT_PREFIX}${JSON.stringify({ blocks: [] })}`;
      const result = deserializeCloudPrompt(payload);
      expect(result).toEqual([{ type: "text", text: payload }]);
    });
  });

  describe("promptBlocksToText", () => {
    it("extracts and joins text blocks", () => {
      const result = promptBlocksToText([
        { type: "text", text: "hello " },
        {
          type: "resource",
          resource: {
            uri: "attachment://f.txt",
            text: "ignored",
            mimeType: "text/plain",
          },
        },
        { type: "text", text: "world" },
      ]);
      expect(result).toBe("hello world");
    });

    it("returns empty string for non-text blocks only", () => {
      expect(
        promptBlocksToText([
          {
            type: "resource",
            resource: {
              uri: "attachment://f.txt",
              text: "content",
              mimeType: "text/plain",
            },
          },
        ]),
      ).toBe("");
    });

    it("returns empty string for empty array", () => {
      expect(promptBlocksToText([])).toBe("");
    });
  });
});
