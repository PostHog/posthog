import { Alert } from "react-native";
import { describe, expect, it, vi } from "vitest";
import { confirmArchiveRunningTask } from "./archiveGuard";

describe("confirmArchiveRunningTask", () => {
  it("archives only when the user confirms", () => {
    const onConfirm = vi.fn();
    confirmArchiveRunningTask("My task", onConfirm);

    expect(Alert.alert).toHaveBeenCalledTimes(1);
    const [title, message, buttons] = vi.mocked(Alert.alert).mock.calls[0];
    expect(title).toBe("Archive running task?");
    expect(message).toContain("My task");
    expect(message).toContain("stop the agent");

    const cancelButton = buttons?.find((b) => b.text === "Cancel");
    const archiveButton = buttons?.find((b) => b.text === "Archive");

    cancelButton?.onPress?.();
    expect(onConfirm).not.toHaveBeenCalled();

    archiveButton?.onPress?.();
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
