import { describe, expect, it, vi } from "vitest";

const toastMock = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@posthog/ui/primitives/toast", () => ({ toast: toastMock }));

import {
  serializeError,
  summarizeError,
  toastError,
  useErrorDetailsStore,
} from "./errorDetails";

describe("serializeError", () => {
  it("pretty-prints plain objects", () => {
    expect(serializeError({ code: 500, message: "boom" })).toBe(
      JSON.stringify({ code: 500, message: "boom" }, null, 2),
    );
  });

  it("reflows the JSON payload embedded in an API error string", () => {
    const message =
      'Failed request: [400] {"type":"validation_error","attr":"model"}';
    expect(serializeError(message)).toBe(
      `Failed request: [400]\n${JSON.stringify(
        { type: "validation_error", attr: "model" },
        null,
        2,
      )}`,
    );
  });

  it("keeps text after the embedded JSON payload", () => {
    const message = 'Failed: {"detail":"nope"} (request id abc123)';
    expect(serializeError(message)).toBe(
      `Failed:\n${JSON.stringify({ detail: "nope" }, null, 2)}\n(request id abc123)`,
    );
  });

  it("returns a plain string unchanged when there's no JSON to reflow", () => {
    expect(serializeError("Not authenticated")).toBe("Not authenticated");
  });

  it("returns a string with non-JSON braces unchanged", () => {
    expect(serializeError("Error: {oops}")).toBe("Error: {oops}");
  });

  it("expands Error instances with message, stack, and enumerable extras", () => {
    const err = Object.assign(new Error("kaput"), { code: "ECONNRESET" });
    const parsed = JSON.parse(serializeError(err));
    expect(parsed.name).toBe("Error");
    expect(parsed.message).toBe("kaput");
    expect(parsed.code).toBe("ECONNRESET");
    expect(typeof parsed.stack).toBe("string");
  });

  it("keeps the cause chain of Error instances", () => {
    const err = new Error("outer", {
      cause: new Error("inner", { cause: "root" }),
    });
    const parsed = JSON.parse(serializeError(err));
    expect(parsed.cause.message).toBe("inner");
    expect(parsed.cause.cause).toBe("root");
  });

  it("elides circular references instead of throwing", () => {
    const obj: Record<string, unknown> = { a: 1 };
    obj.self = obj;
    const parsed = JSON.parse(serializeError(obj));
    expect(parsed.self).toBe("[circular]");
  });

  it("elides self-referencing Errors instead of degrading to String()", () => {
    const err = new Error("loop");
    Object.assign(err, { self: err });
    const parsed = JSON.parse(serializeError(err));
    expect(parsed.message).toBe("loop");
    expect(parsed.self).toBe("[circular]");
  });

  it("coerces bigints instead of degrading the whole payload", () => {
    const parsed = JSON.parse(serializeError({ id: 10n, note: "x" }));
    expect(parsed.id).toBe("10");
    expect(parsed.note).toBe("x");
  });

  it("falls back to String() for values JSON cannot represent", () => {
    expect(serializeError(undefined)).toBe("undefined");
  });
});

describe("summarizeError", () => {
  it.each([
    ["a string error", "it broke", "it broke"],
    ["an Error's message", new Error("nope"), "nope"],
    ["a message-bearing object", { message: "denied", code: 403 }, "denied"],
  ])("uses %s", (_label, input, expected) => {
    expect(summarizeError(input)).toBe(expected);
  });

  it("flattens whitespace and truncates long messages with an ellipsis", () => {
    const summary = summarizeError(`x  y\n${"z".repeat(300)}`);
    expect(summary.startsWith("x y z")).toBe(true);
    expect(summary.length).toBe(141);
    expect(summary.endsWith("…")).toBe(true);
  });

  it("stringifies messageless payloads", () => {
    expect(summarizeError({ status: 502 })).toBe('{ "status": 502 }');
  });

  it("never returns an empty summary", () => {
    expect(summarizeError("   ")).toBe("Unknown error");
  });
});

describe("toastError", () => {
  const rawError =
    'Failed request: [400] {"detail":"This field is required.","attr":"model"}';

  it("shows a summary in the toast, not the raw payload, with a Details action", () => {
    toastMock.error.mockClear();
    useErrorDetailsStore.getState().close();

    toastError("Couldn't start generation", rawError);

    const [title, options] = toastMock.error.mock.calls[0] as [
      string,
      { description: string; action: { label: string; onClick: () => void } },
    ];
    expect(title).toBe("Couldn't start generation");
    expect(options.description).toBe(summarizeError(rawError));
    expect(options.description.length).toBeLessThanOrEqual(141);

    expect(options.action.label).toBe("Details");
    options.action.onClick();
    const detail = useErrorDetailsStore.getState().detail;
    expect(detail?.title).toBe("Couldn't start generation");
    expect(detail?.error).toBe(rawError);
    useErrorDetailsStore.getState().close();
  });
});
