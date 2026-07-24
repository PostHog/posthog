import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { beforeEach, expect, it, vi } from "vitest";
import { ensurePersonalChannel } from "./ensurePersonalChannel";

function channel(id: string, name = "me"): Channel {
  return { id, name, path: `/${name}`, type: "folder" } as Channel;
}

// The module memoises the created folder, so each test needs a fresh copy.
beforeEach(() => {
  vi.resetModules();
});

it("returns the existing folder without creating", async () => {
  const create = vi.fn();
  const existing = channel("1");
  await expect(ensurePersonalChannel([existing], create)).resolves.toBe(
    existing,
  );
  expect(create).not.toHaveBeenCalled();
});

it("shares one create between callers racing before it settles", async () => {
  const { ensurePersonalChannel: ensure } = await import(
    "./ensurePersonalChannel"
  );
  const create = vi.fn(
    () => new Promise<Channel>((r) => setTimeout(() => r(channel("1")), 5)),
  );

  const [a, b] = await Promise.all([ensure([], create), ensure([], create)]);

  expect(create).toHaveBeenCalledTimes(1);
  expect(a).toBe(b);
});

it("doesn't create a second folder for a caller still holding the pre-create list", async () => {
  const { ensurePersonalChannel: ensure } = await import(
    "./ensurePersonalChannel"
  );
  const create = vi.fn(async () => channel("1"));

  // First caller creates it. The cache is seeded, but a component that hasn't
  // re-rendered yet still passes the empty list it captured last render.
  await ensure([], create);
  const second = await ensure([], create);

  expect(create).toHaveBeenCalledTimes(1);
  expect(second.id).toBe("1");
});

it("prefers the list once it carries the folder, so a recreated me isn't stale", async () => {
  const { ensurePersonalChannel: ensure } = await import(
    "./ensurePersonalChannel"
  );
  const create = vi.fn(async () => channel("1"));
  await ensure([], create);

  // "me" was deleted and remade elsewhere; the list is authoritative.
  const fresh = channel("2");
  await expect(ensure([fresh], create)).resolves.toBe(fresh);
  // …and the stale memo is dropped rather than resurfacing afterwards.
  await expect(ensure([fresh], create)).resolves.toBe(fresh);
  expect(create).toHaveBeenCalledTimes(1);
});

it("lets a later caller retry after a failed create", async () => {
  const { ensurePersonalChannel: ensure } = await import(
    "./ensurePersonalChannel"
  );
  const create = vi
    .fn<() => Promise<Channel>>()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(channel("1"));

  await expect(ensure([], create)).rejects.toThrow("offline");
  await expect(ensure([], create)).resolves.toEqual(channel("1"));
  expect(create).toHaveBeenCalledTimes(2);
});
