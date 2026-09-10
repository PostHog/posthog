import type { Meta, StoryObj } from "@storybook/react-vite";
import { GatewayConnectDialog } from "./GatewayConnectDialog";

const meta = {
  title: "MCP gateway/GatewayConnectDialog",
  component: GatewayConnectDialog,
  args: {
    open: true,
    serverName: "Internal wiki",
    onSubmit: () => {},
    onClose: () => {},
  },
} satisfies Meta<typeof GatewayConnectDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

/** A teammate added this custom server with an API key: each member enters their own. */
export const CustomServerAddedWithApiKey: Story = {
  args: { fixedAuthType: "api_key", isCustomServer: true },
};

/** A custom OAuth server keeps the optional client id and secret. */
export const CustomServerAddedWithOAuth: Story = {
  args: { fixedAuthType: "oauth", isCustomServer: true },
};

/** Custom servers registered before their auth type was recorded still let the member choose. */
export const CustomServerWithoutRecordedAuthType: Story = {
  args: { fixedAuthType: null, isCustomServer: true },
};

export const CatalogApiKeyTemplate: Story = {
  args: { fixedAuthType: "api_key", serverName: "Linear" },
};
