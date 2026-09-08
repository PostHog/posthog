import { DragDropProvider } from "@dnd-kit/react";
import { ChatCenteredText, Globe, Terminal } from "@phosphor-icons/react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { BrowserPanelChrome } from "../../embedded-browser/BrowserPanel";
import type { PanelContent } from "../panelTypes";
import { TabbedPanel } from "./TabbedPanel";

function placeholder(label: string) {
  return (
    <div className="flex h-full items-center justify-center bg-(--gray-2) text-(--gray-10) text-sm">
      {label}
    </div>
  );
}

const content: PanelContent = {
  id: "main-panel",
  activeTabId: "browser-1",
  droppable: true,
  tabs: [
    {
      id: "logs",
      label: "Chat",
      data: { type: "logs" },
      closeable: false,
      draggable: true,
      icon: <ChatCenteredText size={14} />,
      component: placeholder("Chat"),
    },
    {
      id: "shell",
      label: "Terminal",
      data: { type: "terminal", terminalId: "shell", cwd: "" },
      closeable: true,
      draggable: true,
      icon: <Terminal size={14} />,
      component: placeholder("Terminal"),
    },
    {
      id: "browser-1",
      label: "PostHog",
      data: {
        type: "browser",
        browserId: "browser-1",
        url: "https://posthog.com",
      },
      closeable: true,
      draggable: true,
      icon: <Globe size={14} />,
      component: (
        <BrowserPanelChrome
          hasPage
          currentUrl="https://posthog.com/"
          pageState={{
            viewId: "task-browser:t1:browser-1",
            url: "https://posthog.com/",
            title: "PostHog",
            canGoBack: true,
            canGoForward: false,
            isLoading: false,
          }}
          loadError={null}
          onNavigate={() => {}}
          onBack={() => {}}
          onForward={() => {}}
          onReload={() => {}}
          onOpenExternal={() => {}}
          onOpenDevTools={() => {}}
        />
      ),
    },
  ],
};

const meta = {
  title: "Panels/TabbedPanel",
  component: TabbedPanel,
  decorators: [
    (Story) => (
      <DragDropProvider>
        <div style={{ height: 420, maxWidth: 900 }}>
          <Story />
        </div>
      </DragDropProvider>
    ),
  ],
} satisfies Meta<typeof TabbedPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * A browser tab alongside the Chat and Terminal tabs, with the "new terminal"
 * and "new browser" tab-bar buttons. In the real app the host paints the live
 * page into the grey area (natively, above the renderer, so it cannot appear
 * in Storybook).
 */
export const WithBrowserTab: Story = {
  args: {
    panelId: "main-panel",
    mountScopeKey: "story",
    content,
    onAddTerminal: () => {},
    onAddBrowser: () => {},
  },
};
