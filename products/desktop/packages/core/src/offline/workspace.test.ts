import { describe, expect, it } from "vitest";
import { savedDraftSchema } from "./schemas";
import { OfflineWorkspace } from "./workspace";

function storage() {
  const data = new Map<string, string>();
  return {
    data,
    read: async (key: string) => data.get(key) ?? null,
    write: async (key: string, value: string) => {
      data.set(key, value);
    },
    remove: async (key: string) => {
      data.delete(key);
    },
  };
}

describe("offline workspace", () => {
  it.each([3, 4, 10])("restores a draft with %i photos", async (count) => {
    const store = storage();
    const draft = {
      text: "Review these images",
      photos: Array.from({ length: count }, (_, i) => ({
        id: `photo-${i}`,
        uri: `file:///example/${i}.jpg`,
        name: `${i}.jpg`,
        mimeType: "image/jpeg",
      })),
    };
    await new OfflineWorkspace(store).write("draft", draft);
    const restored = await new OfflineWorkspace(store).read("draft", 1000);
    expect(savedDraftSchema.parse(restored)).toEqual(draft);
  });

  it("does not resurrect a cleared draft after pending writes", async () => {
    const store = storage();
    const workspace = new OfflineWorkspace(store);
    const first = workspace.write("draft", { text: "First" });
    const second = workspace.write("draft", { text: "Second" });
    const clear = workspace.remove("draft");
    await Promise.all([first, second, clear]);
    expect(await workspace.read("draft", 1000)).toBeNull();
  });

  it("drops expired and malformed records", async () => {
    const store = storage();
    const workspace = new OfflineWorkspace(store);
    store.data.set(
      "draft",
      JSON.stringify({
        version: 1,
        savedAt: Date.now() - 2000,
        value: { text: "old" },
      }),
    );
    expect(await workspace.read("draft", 1000)).toBeNull();
    expect(store.data.has("draft")).toBe(false);
    store.data.set("draft", '{"version":1,"value":{}}');
    expect(await workspace.read("draft", 1000)).toBeNull();
  });

  it("rejects late writes after account cleanup", async () => {
    const workspace = new OfflineWorkspace(storage());
    await workspace.write("draft", { text: "Saved" });
    await workspace.close();
    await expect(workspace.write("draft", { text: "Late" })).rejects.toThrow(
      "Workspace closed",
    );
    expect(await workspace.read("draft", 1000)).toBeNull();
  });
});
