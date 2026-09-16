import {
  DISMISSAL_REASON_OPTIONS,
  isDismissalReasonSnooze,
} from "@posthog/shared";
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

function renderSheet(visible = true, extraProps: { hasOpenPr?: boolean } = {}) {
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
        ...extraProps,
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

function findRadioByLabel(
  renderer: ReturnType<typeof create>,
  label: string,
): ReactTestInstance {
  const matches = renderer.root.findAll(
    (n) =>
      n.props?.accessibilityLabel === label &&
      typeof n.props?.onPress === "function",
  );
  if (matches.length === 0) throw new Error(`No radio for ${label}`);
  return matches[0];
}

function findGroupByLabel(
  renderer: ReturnType<typeof create>,
  label: string,
): ReactTestInstance {
  const matches = renderer.root.findAll(
    (n) =>
      n.props?.accessibilityLabel === label &&
      n.props?.accessibilityRole === "radiogroup",
  );
  if (matches.length === 0) throw new Error(`No group for ${label}`);
  return matches[0];
}

function hasTextNode(
  renderer: ReturnType<typeof create>,
  content: string,
): boolean {
  return (
    renderer.root.findAll((n) => n.props?.children === content).length > 0
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

  it("groups reasons by outcome and shows the outcome line below the note", () => {
    const { renderer } = renderSheet(true);

    const pauseGroup = findGroupByLabel(
      renderer,
      "Pause until a new matching signal",
    );
    const hideGroup = findGroupByLabel(renderer, "Don't surface again");

    const optionValuesIn = (group: ReactTestInstance): string[] => {
      const seen = new Set<string>();
      const labels: string[] = [];
      for (const n of group.findAll(
        (node) =>
          node.props?.accessibilityRole === "radio" &&
          typeof node.props?.accessibilityLabel === "string" &&
          typeof node.props?.onPress === "function",
      )) {
        const label = String(n.props.accessibilityLabel).replace(
          "Dismissal reason: ",
          "",
        );
        if (seen.has(label)) continue;
        seen.add(label);
        labels.push(label);
      }
      return labels;
    };

    const expectedPause = DISMISSAL_REASON_OPTIONS.filter((o) =>
      isDismissalReasonSnooze(o.value),
    ).map((o) => o.label);
    const expectedHide = DISMISSAL_REASON_OPTIONS.filter(
      (o) => !isDismissalReasonSnooze(o.value),
    ).map((o) => o.label);

    expect(optionValuesIn(pauseGroup)).toEqual(expectedPause);
    expect(optionValuesIn(hideGroup)).toEqual(expectedHide);

    pressByLabel(renderer, `Dismissal reason: ${expectedPause[0]}`);
    expect(
      findRadioByLabel(renderer, `Dismissal reason: ${expectedPause[0]}`).props
        .accessibilityState.checked,
    ).toBe(true);
    expect(
      hasTextNode(
        renderer,
        "The report comes back if another matching signal arrives.",
      ),
    ).toBe(true);

    pressByLabel(renderer, `Dismissal reason: ${expectedHide[0]}`);
    expect(
      hasTextNode(renderer, "Matching signals won't surface the report again."),
    ).toBe(true);
  });

  it("appends the pull request outcome when the report has an open PR", () => {
    const { renderer } = renderSheet(true, { hasOpenPr: true });
    const hideValue = DISMISSAL_REASON_OPTIONS.find(
      (o) => !isDismissalReasonSnooze(o.value),
    );
    if (!hideValue) throw new Error("no hide option");

    pressByLabel(renderer, `Dismissal reason: ${hideValue.label}`);

    expect(
      hasTextNode(
        renderer,
        "Matching signals won't surface the report again. The open pull request will be closed.",
      ),
    ).toBe(true);
  });

  it("selects the other reason when a note is typed with no reason picked", () => {
    const { renderer } = renderSheet(true);

    act(() => {
      noteInput(renderer).props.onChangeText("Some detail");
    });

    const otherOption = findRadioByLabel(
      renderer,
      "Dismissal reason: Something else…",
    );
    expect(otherOption.props.accessibilityState.checked).toBe(true);
  });

  it("keeps the picked reason when the user then adds a note", () => {
    const { renderer } = renderSheet(true);

    pressByLabel(renderer, `Dismissal reason: ${FIRST_REASON.label}`);
    act(() => {
      noteInput(renderer).props.onChangeText("extra context");
    });

    const firstOption = findRadioByLabel(
      renderer,
      `Dismissal reason: ${FIRST_REASON.label}`,
    );
    expect(firstOption.props.accessibilityState.checked).toBe(true);
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
