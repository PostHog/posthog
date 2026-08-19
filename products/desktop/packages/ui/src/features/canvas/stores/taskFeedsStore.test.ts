import { beforeEach, describe, expect, it } from "vitest";
import { useTaskFeedsStore } from "./taskFeedsStore";

describe("taskFeedsStore", () => {
  beforeEach(() => {
    useTaskFeedsStore.setState({ feeds: [] });
  });

  it("stores a new feed with trimmed name and query", () => {
    const feed = useTaskFeedsStore
      .getState()
      .addFeed({ name: "  Billing work  ", query: " billing " });

    expect(feed.name).toBe("Billing work");
    expect(feed.query).toBe("billing");
    expect(useTaskFeedsStore.getState().feeds).toEqual([feed]);
  });

  it("updates only the fields the patch names", () => {
    const feed = useTaskFeedsStore
      .getState()
      .addFeed({ name: "Billing work", query: "billing" });

    useTaskFeedsStore.getState().updateFeed(feed.id, { query: " invoices " });

    const updated = useTaskFeedsStore.getState().feeds[0];
    expect(updated.name).toBe("Billing work");
    expect(updated.query).toBe("invoices");
    expect(updated.id).toBe(feed.id);
  });

  it("removes only the named feed", () => {
    const keep = useTaskFeedsStore
      .getState()
      .addFeed({ name: "Keep", query: "keep" });
    const drop = useTaskFeedsStore
      .getState()
      .addFeed({ name: "Drop", query: "drop" });

    useTaskFeedsStore.getState().removeFeed(drop.id);

    expect(useTaskFeedsStore.getState().feeds).toEqual([keep]);
  });
});
