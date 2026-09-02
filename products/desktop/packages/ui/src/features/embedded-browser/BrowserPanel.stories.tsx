import type { Meta, StoryObj } from "@storybook/react-vite";
import { BrowserPanelChrome } from "./BrowserPanel";
import type { EmbeddedBrowserPageState } from "./useEmbeddedBrowser";

function pageState(
  overrides: Partial<EmbeddedBrowserPageState> = {},
): EmbeddedBrowserPageState {
  return {
    viewId: "task-browser:t1:browser-1",
    url: "http://localhost:3000/",
    title: "My app",
    canGoBack: true,
    canGoForward: false,
    isLoading: false,
    ...overrides,
  };
}

const meta = {
  title: "Embedded Browser/BrowserPanelChrome",
  component: BrowserPanelChrome,
  decorators: [
    (Story) => (
      <div style={{ height: 420, maxWidth: 900 }}>
        <Story />
      </div>
    ),
  ],
  args: {
    onNavigate: () => {},
    onBack: () => {},
    onForward: () => {},
    onReload: () => {},
    onOpenExternal: () => {},
    onOpenDevTools: () => {},
  },
} satisfies Meta<typeof BrowserPanelChrome>;

export default meta;
type Story = StoryObj<typeof meta>;

/** A brand-new browser tab: no page yet, the URL bar is the only affordance. */
export const FreshTab: Story = {
  args: {
    hasPage: false,
    currentUrl: "",
    pageState: null,
    loadError: null,
  },
};

/**
 * A page is open (in the real app the host paints the live page into the grey
 * slot area — natively, above the renderer, so it cannot appear here).
 */
export const PageOpen: Story = {
  args: {
    hasPage: true,
    currentUrl: "http://localhost:3000/",
    pageState: pageState(),
    loadError: null,
  },
};

/** Main-frame load failure: banner with the error and a retry. */
export const LoadFailed: Story = {
  args: {
    hasPage: true,
    currentUrl: "http://localhost:3000/",
    pageState: pageState({ canGoBack: false }),
    loadError: "net::ERR_CONNECTION_REFUSED",
  },
};
