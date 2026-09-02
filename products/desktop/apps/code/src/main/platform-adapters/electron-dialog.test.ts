import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGetFocusedWindow = vi.hoisted(() => vi.fn());
const mockGetAllWindows = vi.hoisted(() => vi.fn());
const mockShowOpenDialog = vi.hoisted(() => vi.fn());
const mockShowMessageBox = vi.hoisted(() => vi.fn());

vi.mock("inversify", () => ({
  injectable: () => (target: unknown) => target,
}));

vi.mock("electron", () => ({
  BrowserWindow: {
    getFocusedWindow: mockGetFocusedWindow,
    getAllWindows: mockGetAllWindows,
  },
  dialog: {
    showOpenDialog: mockShowOpenDialog,
    showMessageBox: mockShowMessageBox,
  },
}));

import { ElectronDialog } from "./electron-dialog";

function makeWindow(overrides: { visible?: boolean } = {}) {
  return {
    isVisible: vi.fn(() => overrides.visible ?? true),
    focus: vi.fn(),
  };
}

describe("ElectronDialog.pickFile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockShowOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: ["/repo"],
    });
  });

  it("parents the picker to the focused window when one exists", async () => {
    const focused = makeWindow();
    mockGetFocusedWindow.mockReturnValue(focused);

    const result = await new ElectronDialog().pickFile({ directories: true });

    expect(result).toEqual(["/repo"]);
    expect(mockShowOpenDialog).toHaveBeenCalledWith(
      focused,
      expect.any(Object),
    );
    // A focused window is already on top, so we never reach the fallback windows.
    expect(mockGetAllWindows).not.toHaveBeenCalled();
  });

  it("falls back to a visible window and focuses it when nothing is focused", async () => {
    mockGetFocusedWindow.mockReturnValue(null);
    const hidden = makeWindow({ visible: false });
    const visible = makeWindow({ visible: true });
    mockGetAllWindows.mockReturnValue([hidden, visible]);

    await new ElectronDialog().pickFile({ directories: true });

    expect(visible.focus).toHaveBeenCalledTimes(1);
    // The dialog must be parented to the visible window, not opened unparented
    // (which is what previously left it stuck behind/off-screen).
    expect(mockShowOpenDialog).toHaveBeenCalledWith(
      visible,
      expect.any(Object),
    );
  });

  it("opens unparented only when there are no windows at all", async () => {
    mockGetFocusedWindow.mockReturnValue(null);
    mockGetAllWindows.mockReturnValue([]);

    await new ElectronDialog().pickFile({ directories: true });

    expect(mockShowOpenDialog).toHaveBeenCalledWith(expect.any(Object));
    expect(mockShowOpenDialog.mock.calls[0]).toHaveLength(1);
  });
});

describe("ElectronDialog.confirm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockShowMessageBox.mockResolvedValue({ response: 0 });
  });

  it("parents the message box to the focused window when one exists", async () => {
    const focused = makeWindow();
    mockGetFocusedWindow.mockReturnValue(focused);

    await new ElectronDialog().confirm({
      title: "Discard?",
      message: "Discard changes?",
      options: ["Cancel", "Discard"],
    });

    expect(mockShowMessageBox).toHaveBeenCalledWith(
      focused,
      expect.any(Object),
    );
  });

  it("falls back to a visible window and focuses it when nothing is focused", async () => {
    mockGetFocusedWindow.mockReturnValue(null);
    const hidden = makeWindow({ visible: false });
    const visible = makeWindow({ visible: true });
    mockGetAllWindows.mockReturnValue([hidden, visible]);

    await new ElectronDialog().confirm({
      title: "Discard?",
      message: "Discard changes?",
      options: ["Cancel", "Discard"],
    });

    expect(visible.focus).toHaveBeenCalledTimes(1);
    expect(mockShowMessageBox).toHaveBeenCalledWith(
      visible,
      expect.any(Object),
    );
  });
});
