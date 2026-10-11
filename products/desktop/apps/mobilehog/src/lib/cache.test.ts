import type { Task } from "@posthog/shared/domain-types";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const stores = new Map<string, Map<string, string>>();
  const session = {
    region: "us",
    host: "https://us.posthog.com",
    apiKey: "key",
    projectId: 1,
    projectName: "Project",
    userId: 7,
    userName: "Max",
  };
  const auth = { session: session as typeof session | null };

  function createMMKV({ id }: { id: string }) {
    let data = stores.get(id);
    if (!data) {
      data = new Map();
      stores.set(id, data);
    }
    const values = data;
    return {
      getString: (key: string) => values.get(key),
      set: (key: string, value: string) => values.set(key, value),
      remove: (key: string) => values.delete(key),
    };
  }

  return { auth, createMMKV, session, stores };
});

vi.mock("react-native-mmkv", () => ({
  createMMKV: mocks.createMMKV,
  deleteMMKV: (id: string) => mocks.stores.delete(id),
}));
vi.mock("expo-secure-store", () => ({
  getItem: () => "secret",
  setItem: vi.fn(),
}));
vi.mock("expo-crypto", () => ({ getRandomBytes: () => new Uint8Array(16) }));
vi.mock("@/lib/auth", () => ({
  useAuth: { getState: () => mocks.auth },
}));

import { lastOpened, loadOpened, recordOpened } from "./cache";

function task(id: string): Task {
  return { id } as Task;
}

beforeEach(() => {
  // cache.ts keeps its store handles, so empty the data instead of dropping it.
  for (const values of mocks.stores.values()) values.clear();
  mocks.auth.session = { ...mocks.session };
});

describe("opened chats", () => {
  it("keeps the most recently opened first without duplicates", () => {
    recordOpened("a");
    recordOpened("b");
    recordOpened("a");

    expect(loadOpened()).toEqual(["a", "b"]);
  });

  it("keeps each project and account separate", () => {
    recordOpened("a");
    mocks.auth.session = { ...mocks.session, projectId: 2 };
    recordOpened("b");
    mocks.auth.session = { ...mocks.session, userId: 8 };
    recordOpened("c");

    expect(loadOpened()).toEqual(["c"]);
    mocks.auth.session = { ...mocks.session, projectId: 2 };
    expect(loadOpened()).toEqual(["b"]);
    mocks.auth.session = { ...mocks.session };
    expect(loadOpened()).toEqual(["a"]);
  });

  it("drops the oldest past the limit", () => {
    for (let index = 0; index < 60; index++) recordOpened(`task-${index}`);

    const opened = loadOpened();
    expect(opened).toHaveLength(50);
    expect(opened[0]).toBe("task-59");
    expect(opened).not.toContain("task-9");
  });

  it("does nothing while signed out", () => {
    mocks.auth.session = null;
    recordOpened("a");
    mocks.auth.session = { ...mocks.session };

    expect(loadOpened()).toEqual([]);
  });
});

describe("lastOpened", () => {
  const recent = ["r1", "r2", "r3", "r4"].map(task);

  it.each([
    {
      name: "fills with recent tasks after the opened ones",
      opened: ["r3"],
      limit: 3,
      expected: ["r3", "r1", "r2"],
    },
    {
      name: "skips opened ids whose task is gone",
      opened: ["deleted", "r4"],
      limit: 2,
      expected: ["r4", "r1"],
    },
    {
      name: "stops at the limit",
      opened: ["r4", "r3", "r2"],
      limit: 2,
      expected: ["r4", "r3"],
    },
    {
      name: "shows recent tasks when nothing was opened",
      opened: [],
      limit: 8,
      expected: ["r1", "r2", "r3", "r4"],
    },
  ])("$name", ({ opened, limit, expected }) => {
    expect(lastOpened(opened, recent, limit).map(({ id }) => id)).toEqual(
      expected,
    );
  });
});
