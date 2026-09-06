import type { Writable } from "node:stream";
import { describe, expect, it } from "vitest";
import { safeStreamWrite } from "./std-stream";

function throwingStream(error: unknown): Writable {
  return {
    write() {
      throw error;
    },
  } as unknown as Writable;
}

function errnoError(code: string): NodeJS.ErrnoException {
  const error: NodeJS.ErrnoException = new Error(code);
  error.code = code;
  return error;
}

describe("safeStreamWrite", () => {
  it.each(["EPIPE", "ERR_STREAM_DESTROYED"])(
    "drops a %s write to a dead pipe",
    (code) => {
      expect(() =>
        safeStreamWrite(throwingStream(errnoError(code)), "chunk"),
      ).not.toThrow();
    },
  );

  it("rethrows a write error that is not a dead pipe", () => {
    const error = errnoError("ENOSPC");
    expect(() => safeStreamWrite(throwingStream(error), "chunk")).toThrow(
      error,
    );
  });
});
