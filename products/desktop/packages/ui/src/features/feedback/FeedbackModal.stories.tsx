import type { Meta, StoryObj } from "@storybook/react-vite";
import { FeedbackModal } from "./FeedbackModal";

const meta = {
  title: "Feedback/Desktop feedback modal",
  component: FeedbackModal,
  args: {
    mode: "feedback",
    onFinished: () => {},
    contextClient: {
      captureScreenshot: () =>
        Promise.resolve(
          "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI4MDAiIGhlaWdodD0iNDUwIj48cmVjdCB3aWR0aD0iODAwIiBoZWlnaHQ9IjQ1MCIgZmlsbD0iIzFkMWYyNCIvPjxyZWN0IHg9IjI0IiB5PSIyNCIgd2lkdGg9IjE4MCIgaGVpZ2h0PSI0MDIiIHJ4PSI4IiBmaWxsPSIjMjkyYzMzIi8+PHJlY3QgeD0iMjI4IiB5PSIyNCIgd2lkdGg9IjU0OCIgaGVpZ2h0PSI3MiIgcng9IjgiIGZpbGw9IiMyOTJjMzMiLz48cmVjdCB4PSIyMjgiIHk9IjEyMCIgd2lkdGg9IjU0OCIgaGVpZ2h0PSIzMDYiIHJ4PSI4IiBmaWxsPSIjMjkyYzMzIi8+PC9zdmc+",
        ),
      readRecentLogs: () =>
        Promise.resolve(
          "[info] Desktop started\n[info] Project loaded\n[warn] Request retried",
        ),
    },
  },
} satisfies Meta<typeof FeedbackModal>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
