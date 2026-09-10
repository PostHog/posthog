import type { Meta, StoryObj } from "@storybook/react-vite";
import { within } from "storybook/test";
import { FeedbackModal } from "./FeedbackModal";

async function createStoryScreenshot(): Promise<string> {
  const canvas = document.createElement("canvas");
  canvas.width = 800;
  canvas.height = 450;
  const context = canvas.getContext("2d");
  if (!context) return "data:image/jpeg;base64,";
  context.fillStyle = "#1d1f24";
  context.fillRect(0, 0, 800, 450);
  context.fillStyle = "#292c33";
  context.fillRect(24, 24, 180, 402);
  context.fillRect(228, 24, 548, 72);
  context.fillRect(228, 120, 548, 306);
  return canvas.toDataURL("image/jpeg", 0.7);
}

const meta = {
  title: "Feedback/Desktop feedback modal",
  component: FeedbackModal,
  args: {
    mode: "feedback",
    onFinished: () => {},
    contextClient: {
      captureScreenshot: createStoryScreenshot,
      readRecentLogs: () => Promise.resolve("[info] Example app log"),
      submitFeedback: () => Promise.resolve(),
    },
  },
} satisfies Meta<typeof FeedbackModal>;

export default meta;
type Story = StoryObj<typeof meta>;

const LONG_LOGS = Array.from(
  { length: 80 },
  (_, index) =>
    `[info] Example app operation ${index + 1} completed successfully`,
).join("\n");

export const Default: Story = {};

export const WithExpandedScreenshot: Story = {
  play: async ({ canvasElement, userEvent }) => {
    const dialog = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      await dialog.findByRole("button", { name: "View screenshot" }),
    );
  },
};

export const WithLogsLoading: Story = {
  args: {
    contextClient: {
      captureScreenshot: createStoryScreenshot,
      readRecentLogs: () => new Promise<string | null>(() => {}),
      submitFeedback: () => Promise.resolve(),
    },
  },
  play: async ({ canvasElement, userEvent }) => {
    const dialog = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      dialog.getByRole("checkbox", { name: "Include recent app logs" }),
    );
  },
};

export const WithAttachments: Story = {
  play: async ({ canvasElement, userEvent }) => {
    const dialog = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      dialog.getByRole("checkbox", { name: "Include recent app logs" }),
    );
    await userEvent.upload(
      dialog.getByLabelText("Choose feedback images"),
      new File(["example image"], "feedback-example.png", {
        type: "image/png",
      }),
    );
    await dialog.findByText("1 attached");
  },
};

export const WithExpandedLogs: Story = {
  args: {
    contextClient: {
      captureScreenshot: createStoryScreenshot,
      readRecentLogs: () => Promise.resolve(LONG_LOGS),
      submitFeedback: () => Promise.resolve(),
    },
  },
  play: async ({ canvasElement, userEvent }) => {
    const dialog = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      await dialog.findByRole("button", { name: "View app logs" }),
    );
  },
};

export const BeforePostHogWeb: Story = {
  args: { mode: "posthog-web" },
};
