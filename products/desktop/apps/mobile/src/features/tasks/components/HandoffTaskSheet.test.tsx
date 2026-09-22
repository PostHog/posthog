import type { Task } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";
import { createElement, type ReactElement } from "react";
import { Pressable } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { handoffMutate, onHandedOff, membersRef, currentUserRef } = vi.hoisted(
  () => ({
    handoffMutate: vi.fn(),
    onHandedOff: vi.fn(),
    membersRef: { current: [] as UserBasic[] },
    currentUserRef: { current: { id: 1 } as { id: number } | undefined },
  }),
);

// The global react-native mock renders Modal through a DOM portal that is a
// no-op under the node test env, so its children never mount. Substitute plain
// host elements for the components the sheet uses so the body is inspectable.
vi.mock("react-native", () => {
  const host = (name: string) => (props: Record<string, unknown>) =>
    createElement(name, props);
  return {
    ActivityIndicator: host("ActivityIndicator"),
    Alert: { alert: vi.fn() },
    FlatList: <T,>({
      data,
      renderItem,
      keyExtractor,
    }: {
      data: readonly T[];
      renderItem: (info: { item: T; index: number }) => ReactElement;
      keyExtractor?: (item: T, index: number) => string;
    }) =>
      createElement(
        "FlatList",
        {},
        (data ?? []).map((item, index) =>
          createElement(
            "FlatListItem",
            { key: keyExtractor?.(item, index) ?? index },
            renderItem({ item, index }),
          ),
        ),
      ),
    Modal: host("Modal"),
    Pressable: host("Pressable"),
    TextInput: host("TextInput"),
    View: host("View"),
  };
});

vi.mock("../hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({ members: membersRef.current, isLoading: false }),
}));

vi.mock("../hooks/useTasks", () => ({
  useHandoffTask: () => ({ mutate: handoffMutate, isPending: false }),
}));

vi.mock("@/features/auth", () => ({
  useUserQuery: () => ({ data: currentUserRef.current }),
}));

vi.mock("@/hooks/useDebouncedValue", () => ({
  useDebouncedValue: (value: unknown) => value,
}));

vi.mock("@/hooks/useScreenInsets", () => ({
  useScreenInsets: () => ({ bottom: () => 0, sheetContentTop: () => 0 }),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: {}, accent: {} }),
}));

vi.mock("@components/text", () => ({
  Text: (props: Record<string, unknown>) => createElement("Text", props),
}));

vi.mock("expo-haptics", () => ({
  impactAsync: vi.fn(),
  ImpactFeedbackStyle: { Medium: "medium" },
}));

vi.mock("phosphor-react-native", () => ({
  Check: (props: Record<string, unknown>) => createElement("Check", props),
  MagnifyingGlass: (props: Record<string, unknown>) =>
    createElement("MagnifyingGlass", props),
}));

function member(id: number, email: string, firstName?: string): UserBasic {
  return { id, uuid: `u-${id}`, email, first_name: firstName };
}

const TASK: Task = {
  id: "task-1",
  task_number: 1,
  slug: "task-1",
  title: "Fix the thing",
  description: "",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  origin_product: "code",
};

function textOf(node: { props: { children?: unknown } }): string {
  const children = node.props.children;
  return Array.isArray(children) ? children.join("") : String(children ?? "");
}

function pressableWithText(tree: ReactTestRenderer, text: string) {
  return tree.root
    .findAllByType(Pressable)
    .find((pressable) =>
      pressable
        .findAll((n) => String(n.type) === "Text")
        .some((t) => textOf(t).includes(text)),
    );
}

function render(task: Task = TASK): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      createElement(HandoffTaskSheet, {
        visible: true,
        task,
        onClose: vi.fn(),
        onHandedOff,
      }),
    );
  });
  return tree;
}

let HandoffTaskSheet: typeof import("./HandoffTaskSheet").HandoffTaskSheet;

describe("HandoffTaskSheet", () => {
  beforeEach(async () => {
    handoffMutate.mockReset();
    handoffMutate.mockImplementation(
      (_vars, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.(),
    );
    onHandedOff.mockReset();
    membersRef.current = [
      member(1, "me@example.com", "Me"),
      member(2, "alice@example.com", "Alice"),
    ];
    currentUserRef.current = { id: 1 };
    ({ HandoffTaskSheet } = await import("./HandoffTaskSheet"));
  });

  it("excludes the current user from the roster", () => {
    const tree = render();
    const emails = tree.root
      .findAll((n) => String(n.type) === "Text")
      .map(textOf);
    expect(emails).toContain("alice@example.com");
    expect(emails).not.toContain("me@example.com");
  });

  it("locks the commit until a colleague is picked and acknowledged", () => {
    const tree = render();
    expect(pressableWithText(tree, "Hand off")?.props.disabled).toBe(true);

    act(() => pressableWithText(tree, "alice@example.com")?.props.onPress());
    expect(pressableWithText(tree, "Hand off")?.props.disabled).toBe(true);

    act(() => pressableWithText(tree, "I understand")?.props.onPress());
    const button = pressableWithText(tree, "Hand off");
    expect(button?.props.disabled).toBe(false);

    act(() => button?.props.onPress());
    expect(handoffMutate).toHaveBeenCalledWith(
      { taskId: "task-1", userId: 2 },
      expect.anything(),
    );
    expect(onHandedOff).toHaveBeenCalled();
  });

  it("warns that the requester can lose access", () => {
    const tree = render();
    const copy = tree.root
      .findAll((n) => String(n.type) === "Text")
      .map(textOf)
      .join(" ");
    expect(copy).toContain("you lose access");
  });
});
