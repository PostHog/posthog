import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const stores = new Map<string, Map<string, string>>();
  const existing = new Set<string>();
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
      contains: (key: string) => values.has(key),
    };
  }

  class MockFile {
    exists: boolean;
    constructor(uri: string) {
      this.exists = existing.has(uri);
    }
  }

  return { auth, createMMKV, existing, MockFile, session, stores };
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
vi.mock("expo-file-system", () => ({ File: mocks.MockFile }));
vi.mock("@/lib/auth", () => ({
  useAuth: { getState: () => mocks.auth },
}));

import type { Photo } from "./attachments";
import {
  accountStore,
  beginSend,
  clearAccountCache,
  keepUnsent,
  loadDraft,
  moveDraft,
  NEW_CHAT_DRAFT,
  saveDraft,
} from "./cache";

function photo(uri: string): Photo {
  return { id: uri, uri, name: "photo.jpg", mimeType: "image/jpeg", size: 3 };
}

function draftIndex(): string[] {
  const store = accountStore(mocks.session as never);
  return JSON.parse(store.getString("draft-1-index") ?? "[]");
}

beforeEach(() => {
  mocks.stores.clear();
  mocks.existing.clear();
  mocks.auth.session = { ...mocks.session };
  clearAccountCache(mocks.session as never);
});

describe("drafts", () => {
  it("restores the text and photos that were saved", () => {
    mocks.existing.add("file:///a.jpg");
    saveDraft("task-1", { text: "hello", photos: [photo("file:///a.jpg")] });

    expect(loadDraft("task-1")).toEqual({
      text: "hello",
      photos: [photo("file:///a.jpg")],
    });
    expect(loadDraft(NEW_CHAT_DRAFT)).toBeNull();
  });

  it("drops photos whose file is gone", () => {
    mocks.existing.add("file:///kept.jpg");
    saveDraft("task-1", {
      text: "look",
      photos: [photo("file:///kept.jpg"), photo("file:///purged.jpg")],
    });

    expect(loadDraft("task-1")?.photos).toEqual([photo("file:///kept.jpg")]);
  });

  it("returns nothing when only missing photos remain", () => {
    saveDraft("task-1", { text: " ", photos: [photo("file:///purged.jpg")] });

    expect(loadDraft("task-1")).toBeNull();
  });

  it("removes the key when the draft is empty", () => {
    saveDraft("task-1", { text: "hello", photos: [] });
    saveDraft("task-1", { text: "  ", photos: [] });

    expect(loadDraft("task-1")).toBeNull();
    expect(draftIndex()).toEqual([]);
  });

  it("drops photos with missing fields", () => {
    mocks.existing.add("file:///a.jpg");
    const { name: _, ...partial } = photo("file:///a.jpg");
    saveDraft("task-1", { text: "look", photos: [partial as Photo] });

    expect(loadDraft("task-1")).toEqual({ text: "look", photos: [] });
  });

  it("ignores index entries that are not strings", () => {
    accountStore(mocks.session as never).set(
      "draft-1-index",
      JSON.stringify([1, "task-1", null]),
    );
    saveDraft("task-2", { text: "two", photos: [] });

    expect(draftIndex()).toEqual(["task-2", "task-1"]);
  });

  it("keeps only the most recent drafts", () => {
    for (let index = 0; index < 51; index++) {
      saveDraft(`task-${index}`, { text: `draft ${index}`, photos: [] });
    }

    expect(loadDraft("task-0")).toBeNull();
    expect(loadDraft("task-1")?.text).toBe("draft 1");
    expect(loadDraft("task-50")?.text).toBe("draft 50");
    expect(draftIndex()).toHaveLength(50);
  });

  it("keeps drafts per project", () => {
    saveDraft(NEW_CHAT_DRAFT, { text: "first project", photos: [] });
    mocks.auth.session = { ...mocks.session, projectId: 2 };

    expect(loadDraft(NEW_CHAT_DRAFT)).toBeNull();
  });

  it("does nothing without a session", () => {
    mocks.auth.session = null;
    saveDraft("task-1", { text: "hello", photos: [] });

    expect(loadDraft("task-1")).toBeNull();
    expect(mocks.stores.size).toBe(0);
  });

  it("is wiped with the account cache", () => {
    saveDraft("task-1", { text: "hello", photos: [] });
    clearAccountCache(mocks.session as never);

    expect(loadDraft("task-1")).toBeNull();
  });

  it("ignores a corrupt entry", () => {
    accountStore(mocks.session as never).set("draft-1-task-1", "{");

    expect(loadDraft("task-1")).toBeNull();
  });

  it("moves a draft and sends later saves to the new key", () => {
    saveDraft("new-1", { text: "typed", photos: [] });
    moveDraft("new-1", "task-1");

    expect(loadDraft("task-1")?.text).toBe("typed");
    expect(draftIndex()).toEqual(["task-1"]);

    saveDraft("new-1", { text: "typed more", photos: [] });

    expect(loadDraft("task-1")?.text).toBe("typed more");
    expect(draftIndex()).toEqual(["task-1"]);
  });
});

describe("keepUnsent", () => {
  const unsent = { text: "sent", photos: [photo("file:///sent.jpg")] };

  it("restores the unsent message into an empty draft", () => {
    expect(keepUnsent({ text: " ", photos: [] }, unsent)).toEqual(unsent);
  });

  it("keeps what was typed since the send", () => {
    const typed = { text: "new", photos: [photo("file:///new.jpg")] };

    expect(keepUnsent(typed, unsent)).toEqual(typed);
    expect(keepUnsent({ text: "new", photos: [] }, unsent)).toEqual({
      text: "new",
      photos: unsent.photos,
    });
  });
});

describe("sending a draft", () => {
  it("keeps the message saved until the send goes out", () => {
    saveDraft("task-1", { text: "hello", photos: [] });
    const settle = beginSend("task-1", { text: "hello", photos: [] });

    expect(loadDraft("task-1")).toBeNull();
    expect(draftIndex()).toEqual(["task-1"]);

    settle(true);

    expect(loadDraft("task-1")).toBeNull();
    expect(draftIndex()).toEqual([]);
  });

  it("keeps text typed during the send after it goes out", () => {
    const settle = beginSend("task-1", { text: "hello", photos: [] });
    saveDraft("task-1", { text: "next", photos: [] });
    settle(true);

    expect(loadDraft("task-1")?.text).toBe("next");
  });

  it("returns the message to the draft when the send fails", () => {
    const settle = beginSend("task-1", { text: "hello", photos: [] });
    saveDraft("task-1", { text: "  ", photos: [] });
    settle(false);

    expect(loadDraft("task-1")?.text).toBe("hello");
  });

  it("restores a send the app did not finish", async () => {
    beginSend("task-1", { text: "hello", photos: [] });
    vi.resetModules();
    const relaunched = await import("./cache");

    expect(relaunched.loadDraft("task-1")?.text).toBe("hello");
    relaunched.saveDraft("task-1", { text: "", photos: [] });
    expect(relaunched.loadDraft("task-1")).toBeNull();
  });

  it("does not write after the project changed", () => {
    const settle = beginSend("task-1", { text: "hello", photos: [] });
    mocks.auth.session = { ...mocks.session, projectId: 2 };
    settle(false);

    expect(loadDraft("task-1")).toBeNull();
    mocks.auth.session = { ...mocks.session };
    expect(loadDraft("task-1")?.text).toBe("hello");
  });

  it("keeps a pending message out of another account", () => {
    beginSend(NEW_CHAT_DRAFT, { text: "private", photos: [] });
    const other = { ...mocks.session, host: "https://eu.posthog.com" };
    mocks.auth.session = other;
    saveDraft(NEW_CHAT_DRAFT, { text: "", photos: [] });

    expect(loadDraft(NEW_CHAT_DRAFT)).toBeNull();
    expect(accountStore(other as never).getString("draft-1-new-chat")).toBe(
      undefined,
    );
  });

  it("drops pending messages with the account cache", () => {
    beginSend(NEW_CHAT_DRAFT, { text: "private", photos: [] });
    clearAccountCache(mocks.session as never);
    saveDraft(NEW_CHAT_DRAFT, { text: "", photos: [] });

    expect(
      accountStore(mocks.session as never).getString("draft-1-new-chat"),
    ).toBe(undefined);
  });
});
