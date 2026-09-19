import { DEFAULT_GATEWAY_MODEL } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/domain-types";
import { createElement } from "react";
import { Alert, Pressable } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReportDetailScreen from "@/app/inbox/[...id]";
import NewTaskScreen from "@/app/task/index";
import { useTaskStore } from "@/features/tasks/stores/taskStore";
import { CreatePrFeedbackSheet } from "./components/CreatePrFeedbackSheet";
import { DiscussReportSheet } from "./components/DiscussReportSheet";
import { SwipeableReportCard } from "./components/SwipeableReportCard";
import { TinderView } from "./components/TinderView";
import { useDismissedReportsStore } from "./stores/dismissedReportsStore";

const mocks = vi.hoisted(() => ({
  params: {} as Record<string, string>,
  createReportTask: vi.fn(),
  createTask: vi.fn(),
  runTask: vi.fn(),
  replace: vi.fn(),
  push: vi.fn(),
  integrations: vi.fn(),
  configReady: true,
}));

vi.mock("react-native", () => {
  const host = (name: string) => (props: Record<string, unknown>) =>
    createElement(name, props);
  return {
    View: host("View"),
    ScrollView: host("ScrollView"),
    Pressable: host("Pressable"),
    TextInput: host("TextInput"),
    ActivityIndicator: host("ActivityIndicator"),
    Modal: host("Modal"),
    Platform: { OS: "ios" },
    Alert: { alert: vi.fn() },
  };
});
vi.mock("@components/text", () => ({ Text: "Text" }));
vi.mock("expo-router", () => ({
  Stack: { Screen: () => null },
  useLocalSearchParams: () => mocks.params,
  useRouter: () => ({ replace: mocks.replace, push: mocks.push }),
}));
vi.mock("expo-linear-gradient", () => ({ LinearGradient: "Gradient" }));
vi.mock("expo-haptics", () => ({
  impactAsync: vi.fn(),
  ImpactFeedbackStyle: { Light: "light", Medium: "medium" },
}));
vi.mock("react-native-keyboard-controller", () => ({
  useKeyboardHandler: vi.fn(),
  useReanimatedKeyboardAnimation: () => ({
    height: { value: 0 },
    progress: { value: 0 },
  }),
}));
vi.mock("@/features/chat", () => ({
  useVoiceRecording: () => ({ status: "idle" }),
}));
vi.mock("@/features/chat/components/MarkdownText", () => ({
  MarkdownText: "Markdown",
}));
vi.mock("@/hooks/useScreenInsets", () => ({
  useScreenInsets: () => ({ insets: { top: 0 }, bottom: () => 0 }),
}));
vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: {},
    accent: {},
    status: {},
    background: "#fff",
    card: "#fff",
  }),
  toRgba: () => "#fff",
}));
vi.mock("@/lib/posthogApiClient", () => ({
  getPostHogApiClient: () => ({
    createSignalReportTask: mocks.createReportTask,
    createTask: mocks.createTask,
    runTaskInCloud: mocks.runTask,
  }),
}));
vi.mock("@/lib/analytics", () => ({
  useAnalytics: () => ({ track: vi.fn() }),
  ANALYTICS_EVENTS: { INBOX_REPORT_ACTION: "report action" },
  computeReportAgeHours: () => 1,
}));
vi.mock("./api", () => ({ getReportRepository: async () => null }));
vi.mock("./components/SwipeableReportCard", () => ({
  SwipeableReportCard: () => null,
}));
vi.mock("./components/ConventionalCommitTag", () => ({
  ConventionalCommitTag: () => null,
}));
vi.mock("@/features/tasks/hooks/useWarmTask", () => ({ useWarmTask: vi.fn() }));
vi.mock("@/features/tasks/hooks/useUserIntegrations", () => ({
  useUserIntegrations: (options: { enabled: boolean }) => {
    mocks.integrations(options);
    return {
      repositoryOptions: [],
      hasGithubIntegration: options.enabled ? true : null,
      isLoading: false,
      getUserIntegrationId: vi.fn(),
    };
  },
}));
vi.mock("@/features/tasks/hooks/useCloudTaskConfigOptions", () => ({
  useCloudTaskConfigOptions: () => ({
    configOptions: [
      { category: "model", currentValue: DEFAULT_GATEWAY_MODEL, options: [] },
    ],
    modelGroups: [],
    hasLiveConfig: false,
    isConfigReady: mocks.configReady,
  }),
}));
vi.mock("@/features/tasks/composer/AgentConfigControls", () => ({
  AgentConfigControls: () => null,
}));
vi.mock("@/features/tasks/composer/DotBackground", () => ({
  DotBackground: () => null,
}));
vi.mock("@/features/tasks/composer/RepositoryPickerInline", () => ({
  RepositoryPickerInline: "RepositoryPicker",
}));
vi.mock("@/features/tasks/components/GitHubConnectionPrompt", () => ({
  GitHubConnectionPrompt: "ConnectGitHub",
}));
vi.mock("@/features/tasks/components/GitHubLoadNotice", () => ({
  GitHubLoadNotice: "GitHubLoadNotice",
}));
vi.mock("@/features/tasks/composer/attachments/AttachmentSheet", () => ({
  AttachmentSheet: () => null,
}));
vi.mock("@/features/tasks/composer/attachments/AttachmentsBar", () => ({
  AttachmentsBar: () => null,
}));
vi.mock("@/features/tasks/composer/attachments/pickers", () => ({
  captureFromCamera: vi.fn(),
  pickDocument: vi.fn(),
  pickPhotoFromLibrary: vi.fn(),
}));
vi.mock("@/features/tasks/composer/attachments/buildCloudPrompt", () => ({
  buildCloudPromptBlocks: vi.fn(),
}));

const report = {
  id: "report-1",
  title: "Fix sample failure",
  summary: "Check the evidence.",
  status: "ready",
  priority: "P2",
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
} as SignalReport;

let renderer: ReactTestRenderer;
async function renderComposer(): Promise<void> {
  await act(async () => {
    renderer = create(createElement(NewTaskScreen));
  });
}
function submitButton() {
  return renderer.root.find(
    (node) =>
      node.type === Pressable &&
      node.props.accessibilityLabel === "Create task",
  );
}
async function renderTriage(): Promise<void> {
  await act(async () => {
    renderer = create(createElement(TinderView, { reports: [report] }));
  });
}
function acceptCard(): Promise<void> {
  return renderer.root.findByType(SwipeableReportCard).props.onAccept(report);
}

describe("Mobile report task launches", () => {
  it.each(["implementation", "discussion"])(
    "keeps the report detail %s intent when opening the composer",
    async (relationship) => {
      mocks.params = { id: report.id };
      await act(async () => {
        renderer = create(createElement(ReportDetailScreen));
      });
      await act(async () => {
        if (relationship === "discussion") {
          renderer.root.findByType(DiscussReportSheet).props.onSubmit({
            prompt: "Discuss the evidence",
            question: "Why did this happen?",
          });
        } else {
          renderer.root
            .findByType(CreatePrFeedbackSheet)
            .props.onSubmit("Add regression coverage");
        }
      });
      const route = mocks.push.mock.calls[0][0];
      expect(route.pathname).toBe("/task");
      expect(route.params).toEqual({
        signalReport: report.id,
        signalReportRelationship: relationship,
        prompt:
          relationship === "discussion"
            ? "Discuss the evidence"
            : expect.stringContaining(report.id),
        ...(relationship === "discussion"
          ? { signalReportDiscussionQuestion: "Why did this happen?" }
          : {}),
      });
      if (relationship === "implementation") {
        expect(route.params.prompt).toContain("Add regression coverage");
      }
    },
  );
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.params = {
      prompt: "Read the report evidence",
      signalReport: report.id,
    };
    mocks.configReady = true;
    mocks.createReportTask.mockResolvedValue({ id: "task-1" });
    mocks.runTask.mockResolvedValue({ id: "run-1" });
    useTaskStore.setState({
      lastRepository: { integrationId: null, repository: null },
    });
    useDismissedReportsStore.getState().clearDismissed();
  });
  afterEach(() => {
    if (renderer) act(() => renderer.unmount());
  });

  it.each(["implementation", "discussion"])(
    "starts a report %s without a personal repository",
    async (relationship) => {
      mocks.params.signalReportRelationship = relationship;
      mocks.params.signalReportDiscussionQuestion = "What caused this?";
      await renderComposer();
      expect(mocks.integrations).toHaveBeenCalledWith({ enabled: false });
      expect(
        renderer.root.findAll(
          (node) => String(node.type) === "RepositoryPicker",
        ),
      ).toHaveLength(0);
      expect(submitButton().props.disabled).toBe(false);
      await act(async () => {
        await submitButton().props.onPress();
      });
      expect(mocks.createReportTask).toHaveBeenCalledWith({
        reportId: report.id,
        relationship,
        question: "What caused this?",
        description: "Read the report evidence",
        title: "Read the report evidence",
      });
      expect(mocks.createTask).not.toHaveBeenCalled();
      expect(mocks.runTask).toHaveBeenCalledWith(
        "task-1",
        undefined,
        expect.objectContaining({
          runSource: "signal_report",
          signalReportId: report.id,
          ...(relationship === "discussion"
            ? { initialPermissionMode: "auto" }
            : {}),
        }),
      );
      expect(mocks.replace).toHaveBeenCalledWith("/task/task-1");
    },
  );

  it("still requires a repository for an ordinary task", async () => {
    mocks.params = { prompt: "Fix a sample failure" };
    await renderComposer();
    expect(submitButton().props.disabled).toBe(true);
    await act(async () => {
      await submitButton().props.onPress();
    });
    expect(mocks.createTask).not.toHaveBeenCalled();
    expect(mocks.createReportTask).not.toHaveBeenCalled();
  });

  it("does not submit twice before the composer rerenders", async () => {
    await renderComposer();
    const press = submitButton().props.onPress;
    await act(async () => {
      await Promise.all([press(), press()]);
    });
    expect(mocks.createReportTask).toHaveBeenCalledOnce();
    expect(mocks.runTask).toHaveBeenCalledOnce();
  });

  it("shows startup errors without navigating to a running task", async () => {
    mocks.runTask.mockRejectedValueOnce(new Error("Cloud start failed"));
    await renderComposer();
    await act(async () => {
      await submitButton().props.onPress();
    });
    expect(Alert.alert).toHaveBeenCalledWith(
      "Could not start task",
      "Cloud start failed",
    );
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("starts one triage implementation and accepts it only after startup", async () => {
    let finish!: () => void;
    mocks.runTask.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    await renderTriage();
    let pending!: Promise<void>;
    await act(async () => {
      pending = acceptCard();
    });
    expect(useDismissedReportsStore.getState().acceptedIds).toEqual([]);
    await act(async () => {
      await acceptCard();
      finish();
      await pending;
    });
    expect(mocks.createReportTask).toHaveBeenCalledOnce();
    expect(mocks.createReportTask).toHaveBeenCalledWith({
      reportId: report.id,
      relationship: "implementation",
      description: expect.stringContaining(report.id),
      title: expect.any(String),
    });
    expect(mocks.runTask).toHaveBeenCalledOnce();
    expect(useDismissedReportsStore.getState().acceptedIds).toEqual([
      report.id,
    ]);
  });

  it("keeps a report in triage when cloud startup fails", async () => {
    mocks.runTask.mockRejectedValueOnce(new Error("Cloud start failed"));
    await renderTriage();
    await act(async () => {
      await acceptCard();
    });
    expect(useDismissedReportsStore.getState().acceptedIds).toEqual([]);
    expect(JSON.stringify(renderer.toJSON())).toContain("Cloud start failed");
  });

  it("does not launch a swipe before cloud configuration is ready", async () => {
    mocks.configReady = false;
    await renderTriage();
    await act(async () => {
      await acceptCard();
    });
    expect(mocks.createReportTask).not.toHaveBeenCalled();
  });
});

vi.mock("posthog-react-native", () => ({
  useFeatureFlag: () => false,
  usePostHog: () => ({ capture: vi.fn() }),
}));
vi.mock("@/features/auth", () => ({
  useUserQuery: () => ({ data: { id: 1 } }),
}));
vi.mock("./hooks/useInboxReports", () => ({
  useInboxReport: () => ({ data: report }),
  useInboxReportArtefacts: () => ({ data: { results: [] } }),
  useInboxReportSignals: () => ({ data: { results: [] } }),
}));
vi.mock("./hooks/useInboxEngagementTracker", () => ({
  useInboxEngagementTracker: () => ({
    signalAction: vi.fn(),
    signalScroll: vi.fn(),
  }),
}));
vi.mock("./components/CreatePrFeedbackSheet", () => ({
  CreatePrFeedbackSheet: () => null,
}));
vi.mock("./components/DiscussReportSheet", () => ({
  DiscussReportSheet: () => null,
}));
vi.mock("./components/DismissReportSheet", () => ({
  DismissReportSheet: () => null,
}));
vi.mock("./components/RefundReportSheet", () => ({
  RefundReportSheet: () => null,
}));
vi.mock("./components/ReportActivity", () => ({ ReportActivity: () => null }));
vi.mock("./components/ReportFeedbackFooter", () => ({
  ReportFeedbackFooter: () => null,
}));
vi.mock("./components/ReportVerdictBanner", () => ({
  ReportVerdictBanner: () => null,
}));
vi.mock("./components/SignalCard", () => ({ SignalCard: () => null }));
vi.mock("./components/SuggestedReviewers", () => ({
  SuggestedReviewers: () => null,
}));
vi.mock("@/features/tasks/components/PrStatusBadge", () => ({
  PrStatusBadge: () => null,
}));
vi.mock("@/lib/openExternalUrl", () => ({ openExternalUrl: vi.fn() }));
