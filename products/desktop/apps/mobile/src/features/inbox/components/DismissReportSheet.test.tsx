import { DISMISSAL_REASON_OPTIONS } from "@posthog/shared";
import { createElement } from "react";
import { act, create, type ReactTestInstance } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDismissDraftStore } from "../stores/dismissDraftStore";

const mocks = vi.hoisted(() => ({
  updateState: vi.fn(),
}));

vi.mock("../hooks/useInboxReports", () => ({
  useDismissReport: () => ({
    mutateAsync: (input: unknown) => mocks.updateState(input),
  }),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: { 9: "#888" }, accent: { 9: "#09f" } }),
}));

vi.mock("expo-haptics", () => ({
  notificationAsync: vi.fn(),
  NotificationFeedbackType: { Success: "success", Error: "error" },
}));

vi.mock("react-native", async () => {
  const actual = await import("react-native-web");
  const { createElement } = await import("react");
  return {
    ...actual,
    Alert: { alert: vi.fn() },
    Platform: {
      OS: "ios",
      select: <T,>(options: { ios?: T; android?: T; default?: T }) =>
        options.ios ?? options.default,
    },
    TextInput: (props: Record<string, unknown>) =>
      createElement("TextInput", props),
    // react-native-web's Modal is portal-based and renders nothing under the
    // node test environment; a pass-through wrapper lets us inspect the tree.
    Modal: (props: { visible?: boolean; children?: unknown }) =>
      props.visible === false
        ? null
        : createElement("Modal", null, props.children as never),
  };
});

import { DismissReportSheet } from "./DismissReportSheet";

const REPORT_ID = "report-1";
const FIRST_REASON = DISMISSAL_REASON_OPTIONS[0];

function renderSheet(visible = true) {
  const onClose = vi.fn();
  const onDismissed = vi.fn();
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(
      createElement(DismissReportSheet, {
        visible,
        reportId: REPORT_ID,
        reportTitle: "Report one",
        onClose,
        onDismissed,
      }),
    );
  });
  if (!renderer) throw new Error("Renderer not created");
  return {
    renderer: renderer as ReturnType<typeof create>,
    onClose,
    onDismissed,
  };
}

function pressByLabel(
  renderer: ReturnType<typeof create>,
  label: string,
): void {
  const node: ReactTestInstance = renderer.root.find(
    (n) => n.props?.accessibilityLabel === label,
  );
  act(() => {
    node.props.onPress();
  });
}

function noteInput(renderer: ReturnType<typeof create>): ReactTestInstance {
  return renderer.root.find(
    (n) =>
      typeof n.props?.onChangeText === "function" &&
      n.props?.multiline === true,
  );
}

describe("DismissReportSheet", () => {
  beforeEach(() => {
    mocks.updateState.mockReset();
    useDismissDraftStore.setState({ drafts: {} });
  });

  it("closes and notifies before the request settles", () => {
    mocks.updateState.mockReturnValue(new Promise(() => {}));
    const { renderer, onClose, onDismissed } = renderSheet(true);

    pressByLabel(renderer, `Dismissal reason: ${FIRST_REASON.label}`);
    pressByLabel(renderer, "Confirm dismissal");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onDismissed).toHaveBeenCalledWith({
      reason: FIRST_REASON.value,
      note: null,
    });
    expect(mocks.updateState).toHaveBeenCalledTimes(1);
  });

  it("mounts open, prefilled, when a prior failure left a retry draft", () => {
    useDismissDraftStore.setState({
      drafts: {
        [REPORT_ID]: {
          reason: FIRST_REASON.value,
          note: "left over",
          reopen: true,
          errorMessage: "was offline",
        },
      },
    });
    const { renderer } = renderSheet(false);

    expect(noteInput(renderer).props.value).toBe("left over");
  });

  it("reopens with the typed reason and note when the write fails", async () => {
    mocks.updateState.mockRejectedValue(new Error("network down"));
    const { renderer } = renderSheet(true);

    pressByLabel(renderer, `Dismissal reason: ${FIRST_REASON.label}`);
    act(() => {
      noteInput(renderer).props.onChangeText("please retry");
    });

    await act(async () => {
      pressByLabel(renderer, "Confirm dismissal");
      await Promise.resolve();
    });

    const stored = useDismissDraftStore.getState().drafts[REPORT_ID];
    expect(stored).toMatchObject({
      reason: FIRST_REASON.value,
      note: "please retry",
      reopen: true,
    });
    expect(noteInput(renderer).props.value).toBe("please retry");
  });
});
