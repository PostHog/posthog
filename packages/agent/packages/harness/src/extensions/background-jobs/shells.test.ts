import { afterEach, describe, expect, it, vi } from "vitest";
import { BackgroundShells } from "./shells";

type Sent = { content: string };

function setup() {
  const sent: Sent[] = [];
  const pi = { sendMessage: vi.fn((message: Sent) => sent.push(message)) };
  const shells = new BackgroundShells(pi as never, () => {}, {
    settleMs: 50,
    minIntervalMs: 50,
  });
  return { shells, sent };
}

describe("BackgroundShells", () => {
  let current: BackgroundShells | null = null;
  afterEach(() => current?.stopAll());

  it("reads only what is new, and tells the agent the exit with the last output", async () => {
    const { shells, sent } = setup();
    current = shells;
    const { id } = shells.start(
      "printf 'a\\nb\\n'; sleep 0.3; printf 'c\\n'",
      process.cwd(),
    );

    await vi.waitFor(() => expect(shells.list()[0]?.lines).toBe(2));
    expect(shells.read(id)?.lines).toEqual(["a", "b"]);
    await vi.waitFor(() =>
      expect(sent.at(-1)?.content).toContain("Exited with code 0"),
    );
    expect(shells.read(id)?.lines).toEqual(["c"]);
    expect(sent.at(-1)?.content).toContain("a\nb\nc");
    expect(shells.status()).toBeUndefined();
  });

  it("wakes the agent once with lines a monitor matched together", async () => {
    const { shells, sent } = setup();
    current = shells;
    shells.start(
      "echo ok; echo 'ERROR one'; echo fine; echo 'error two'; sleep 5",
      process.cwd(),
      [{ pattern: "error", label: "errors" }],
    );

    await vi.waitFor(() => expect(sent.length).toBe(1));
    expect(sent[0].content).toContain('Monitor "errors"');
    expect(sent[0].content.split("\n").slice(1)).toEqual([
      "ERROR one",
      "error two",
    ]);
    expect(shells.status()).toBe("1 shell · 1 monitor");
  });

  it("takes input on stdin and stops the shell with what it started", async () => {
    const { shells, sent } = setup();
    current = shells;
    const { id } = shells.start(
      "read line; echo got:$line; sleep 30 & wait",
      process.cwd(),
    );

    expect(shells.write(id, "hi\n")).toBe(true);
    await vi.waitFor(() => expect(shells.read(id)?.lines).toEqual(["got:hi"]));
    expect(shells.stop(id)).toBe(true);
    await vi.waitFor(() => expect(shells.list()[0]?.running).toBe(false));
    expect(sent.at(-1)?.content).toContain("Exited");
  });

  it("refuses a bad monitor pattern before starting anything", () => {
    const { shells } = setup();
    expect(() =>
      shells.start("sleep 30", process.cwd(), [{ pattern: "(" }]),
    ).toThrow();
    expect(shells.list()).toEqual([]);
  });
});
