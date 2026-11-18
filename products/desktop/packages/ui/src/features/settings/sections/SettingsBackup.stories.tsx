import type { BackupReview } from "@posthog/core/settings/settingsBackup";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SettingsBackupView } from "./SettingsBackup";

const previewAudio =
  "data:audio/wav;base64,UklGRmQGAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YUAGAAAAAHYP1BohHz8bORD5AILx4eUj4YLkFe8S/oYNZBmRHrUblhHfAnPzWufC4Rzkx+00/JUL4xfkHQkc1BK0BGL14+h94tnjmOxp+qcJUxYbHTwc9BN1Bk/3eepT47jjiOuy+L0HtxQ4HE0c9BQhCDX5G+xD5LfjmOoS99oFEBM8Gz0c1BW2CRT7x+1K5dbjx+mJ9QAEYREqGg4clRYzC+n8eO9o5hTkFukY9DACrQ8CGcEbNheXDLP+L/GY53DkhejB8m4A9Q3JF1gbtxfhDW0A5/Lb6OjkFOiF8bv+PAx+FtIaGRgPDxkCoPQt6nvlwudk8Bf9hAolFTIaXBgiELQDV/aM6yfmjudf74b7zwjAE3oZgBgZETwFCfj27Ovmeed27gf6IAdREqsYhxj0EbAGtflq7sXngeeq7Z74eAXaEMYXcRixEg8IWfvl77Popef77Er32QNcD84WPxhSE1cJ8vxk8bTp5Odp7A32RQLbDcUV8xfWE4gKgP7m8sXqPejz6+j0vgBZDKwUjRc9FKELAABp9OXrr+ia69zzRv/WCoYTDxeIFKEMcQHq9RLtOelc6+jy3f1WCVQSexa4FIgN0QJo90nu2Ok66w7yhfzbBxgR0RXNFFUOIATh+Invi+oz607xP/tlBtUPFBXIFAgPXAVT+s/wUetF66jwDfr4BIsORRSpFKEPhAa7+xvyKOxv6xzw8PiUAz8NZxNyFCAQlwca/WnzDu2y66rv5/c7AvALehIlFIUQlQhs/rf0Au4L7FLv9fbvAKIKgBHBE9EQfAmx/wX2Ae947BLvGfay/1UJfBBJEwQRTArnAFD3CfD67OvuVfWE/gwIbw++Eh8RBQsNApb4GvGO7dzup/Rm/ckGWw4iEiMRpwsiA9b5MfIz7uTuEfRa/I0FQg11EQ8RMQwmBA77S/Pn7gLvk/Ng+1oEJgy6EOcQpAwWBTz8afSo7zbvK/N5+jADCQvzD6kQAA3zBWD9hvV18H3v2vKm+RMC6wkgD1gQRQ28Bnf+o/ZM8dfvoPLo+AIB0AhFDvUPdA1wB4H/vPcs8kPwfPI++AAAuAdhDYEPjg0PCHsA0vgT87/wbvKp9w3/pgZ4DP4Okg2aCGcB4fn+80nxc/Ip9yn+mwWLC2wOgg0PCUIC6Prt9OHxjfK+9lb9lwSbCs4NXw1wCQwD5/vd9YXyufJo9pX8ngOqCSYNKg27CcUD2/zO9jLz9/Im9ub7rwK7CHQM5AzzCWsExP289+jzRfP59Un7zAHOB7oLjgwWCv4EoP6o+KX0o/Pf9b/69wDkBvoKKQwnCn8Fb/+O+Wf1DvTY9Uj6LwABBjYKuAslCuwFLgBv+i32hvTj9eT5d/8kBW8JOgsRCkcG3wBH+/X2CfX/9ZP5zv5QBKcIsgrsCY8GgAEX/L73lvUs9lT5Nf6FA98HIQq4CcQGEQLd/IX4K/Zo9ij5rf3EAhgHiAl1CecGkQKY/Ur5xvay9g75Nv0PAlUG6ggkCfkG/wJG/gr6Z/cJ9wX50PxnAZcFRwjHCPkGXQPo/sb6C/hs9w35e/zNAN8EogdfCOkGqQN7/3r7sfjZ9yT5OPxAAC8E+wbtB8oG4wMAACf8WPlP+Ev5BvzE/4cDVQZzB5wGDQR2AMr8/vnM+ID55PtV/+gCsAXzBmEGJgTcAGP9ovpQ+cH50/v3/lUCDgVtBhkGLwQzAfH9QfvY+Q/60vuo/s0BcQTjBcYFKAR6AXL+3Ptj+mf64ftp/lIB2QNWBWkFEgSwAef+cPzw+sn6/vs7/uQASQPJBAMF7gPXAU7//Px++zL7Kfwc/oQAwQI8BJYEvQPtAab/gP0K/KP7YfwN/jMAQgKxAyMEfwP1AfD/+f2T/Bj8pfwO/vH/zgEqA6sDNQPsASoAaP4Z/ZL88/wd/r7/ZQGnAjAD4gLWAVYAy/6Z/Q79TP07/pr/CQEqArMChQKxAXMAIf8S/oz9rP1m/oX/uQC0ATYCIAJ/AYAAav+E/gn+Ff6f/n//dwBHAbkBtQFAAX4Apf/t/oT+g/7j/on/QwDjAD8BRQH2AG0A0v9L//z+9f4z/6H/HgCKAMkA0AChAE4A8P+f/3D/a/+N/8f/BwA8AFkAWQBDACAA///m/93/4//v//z/";

const review: BackupReview = {
  backup: {
    format: "posthog-desktop-settings",
    formatVersion: 1,
    appVersion: "1.3.0",
    exportedAt: "2026-01-12T12:00:00.000Z",
    settings: {},
    sounds: [],
  },
  settings: {
    theme: "dark",
    completionSound: "random-custom",
    completionVolume: 75,
    customInstructions: "Use short sentences.",
  },
  sounds: [
    {
      id: "chime",
      name: "My chime",
      durationMs: 100,
      dataUrl: previewAudio,
    },
    {
      id: "bell",
      name: "Little bell",
      durationMs: 100,
      dataUrl: previewAudio,
    },
  ],
  warnings: [],
  currentVersion: "1.3.0",
};
const meta: Meta<typeof SettingsBackupView> = {
  title: "Settings/Backup",
  component: SettingsBackupView,
  decorators: [
    (Story) => (
      <div className="mx-auto my-8 w-full max-w-160 px-4">
        <Story />
      </div>
    ),
  ],
  args: {
    soundCount: 4,
    scope: "all",
    busy: null,
    review: null,
    error: null,
    message: null,
    onScopeChange: () => {},
    onExport: () => {},
    onOpen: () => {},
    onImport: () => {},
    onCancel: () => {},
  },
};
export default meta;
type Story = StoryObj<typeof SettingsBackupView>;
export const Default: Story = {};
export const SoundsOnly: Story = { args: { scope: "sounds" } };
export const Review: Story = { args: { review } };
export const CompatibilityWarnings: Story = {
  args: {
    review: {
      ...review,
      currentVersion: "1.4.0",
      warnings: [
        { key: "completionVolume", reason: "changed" },
        { key: "removedPreference", reason: "unknown" },
        { key: "Sound 3", reason: "sound" },
      ],
    },
  },
};
export const Importing: Story = { args: { review, busy: "import" } };
export const SaveFailed: Story = {
  args: {
    review,
    error: "Could not save settings. Check available disk space and try again.",
  },
};
