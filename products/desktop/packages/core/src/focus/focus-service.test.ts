import { beforeEach, describe, expect, it, vi } from "vitest";
import { FocusHostService } from "./focus-service";

describe("FocusHostService event subscriptions", () => {
  const branchUnsubscribe = vi.fn();
  const foreignUnsubscribe = vi.fn();
  const branchSubscribe = vi.fn(() => ({ unsubscribe: branchUnsubscribe }));
  const foreignSubscribe = vi.fn(() => ({ unsubscribe: foreignUnsubscribe }));

  const createService = () =>
    new FocusHostService(
      {
        focus: {
          onBranchRenamed: { subscribe: branchSubscribe },
          onForeignBranchCheckout: { subscribe: foreignSubscribe },
        },
      } as never,
      {} as never,
      {} as never,
    );

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not connect to the workspace server during construction", () => {
    createService();

    expect(branchSubscribe).not.toHaveBeenCalled();
    expect(foreignSubscribe).not.toHaveBeenCalled();
  });

  it("replaces event subscriptions after the workspace server restarts", () => {
    const service = createService();

    service.resubscribeEvents();
    service.resubscribeEvents();

    expect(branchSubscribe).toHaveBeenCalledTimes(2);
    expect(foreignSubscribe).toHaveBeenCalledTimes(2);
    expect(branchUnsubscribe).toHaveBeenCalledOnce();
    expect(foreignUnsubscribe).toHaveBeenCalledOnce();
  });
});
