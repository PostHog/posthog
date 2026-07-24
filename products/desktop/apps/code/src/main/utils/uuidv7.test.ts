import { describe, expect, it, vi } from "vitest";
import { uuidv7 } from "./uuidv7";

const UUID_V7 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("uuidv7", () => {
  it("produces a valid v7 string (version nibble 7, variant 10)", () => {
    for (let i = 0; i < 100; i++) {
      expect(uuidv7()).toMatch(UUID_V7);
    }
  });

  it("encodes the current time so ids sort in creation order", () => {
    const before = Date.now();
    const id = uuidv7();
    const after = Date.now();

    const stampMs = Number.parseInt(id.slice(0, 8) + id.slice(9, 13), 16);
    expect(stampMs).toBeGreaterThanOrEqual(before);
    expect(stampMs).toBeLessThanOrEqual(after);
  });

  it("is unique across rapid calls", () => {
    const ids = new Set(Array.from({ length: 1000 }, () => uuidv7()));
    expect(ids.size).toBe(1000);
  });

  it("writes the 48-bit millisecond timestamp big-endian into the first 6 bytes", () => {
    vi.spyOn(Date, "now").mockReturnValue(0x0123456789ab);
    try {
      const id = uuidv7();
      expect(id.slice(0, 8)).toBe("01234567");
      expect(id.slice(9, 13)).toBe("89ab");
    } finally {
      vi.restoreAllMocks();
    }
  });
});
