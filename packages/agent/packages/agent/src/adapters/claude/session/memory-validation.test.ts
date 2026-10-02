import { describe, expect, it } from "vitest";
import { serializeValidation, validationCommandKey } from "./memory-validation";

describe("validationCommandKey", () => {
  it.each([
    [
      "pnpm --filter=frontend typescript:check 2>&1 | tail -8",
      "pnpm --filter=frontend typescript:check",
    ],
    [
      "cd /tmp/project && pnpm test src/small.test.ts",
      "cd /tmp/project && pnpm test src/small.test.ts",
    ],
    ["uv run pytest tests/unit", "uv run pytest tests/unit"],
    ["cargo test --jobs 1", "cargo test --jobs 1"],
    ["go build ./cmd/demo", "go build ./cmd/demo"],
    ["git status", undefined],
    ['echo "pnpm test"', undefined],
    ["cat test-output.txt", undefined],
  ])("recognizes validation scope in %s", (command, expected) => {
    expect(validationCommandKey(command)).toBe(expected);
    if (expected) {
      expect(validationCommandKey(serializeValidation(command))).toBe(expected);
    }
  });
});
