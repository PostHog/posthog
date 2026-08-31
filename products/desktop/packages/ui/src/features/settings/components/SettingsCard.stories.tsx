import { Button, Switch } from "@posthog/quill";
import { NotificationDeliveryCard } from "@posthog/ui/features/settings/components/NotificationDeliveryCard";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { SettingsSegmented } from "@posthog/ui/features/settings/components/SettingsSegmented";
import { SettingsSelect } from "@posthog/ui/features/settings/components/SettingsSelect";
import { ThemePicker } from "@posthog/ui/features/settings/components/ThemePicker";
import type { ThemePreference } from "@posthog/ui/shell/themeStore";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

const meta: Meta = {
  title: "Settings/SettingsKit",
  // Match the settings page content column so cards size realistically.
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1.5rem" }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj;

export const GeneralPage: Story = {
  render: function GeneralPageStory() {
    const [theme, setTheme] = useState<ThemePreference>("dark");
    const [startIn, setStartIn] = useState("plan");
    const [localMode, setLocalMode] = useState("queue");
    const [cloudMode, setCloudMode] = useState("steer");
    const [sendWith, setSendWith] = useState("enter");
    const [convert, setConvert] = useState("2500");
    const [keepAwake, setKeepAwake] = useState(false);

    return (
      <div className="flex flex-col gap-7">
        <SettingsSection label="Appearance">
          <ThemePicker value={theme} onChange={setTheme} />
        </SettingsSection>

        <SettingsSection
          label="New tasks"
          description="Defaults for every new task. You can change any of these per task in the composer."
        >
          <SettingsCard>
            <SettingsCardRow label="Start in">
              <SettingsSegmented
                ariaLabel="Initial task mode"
                value={startIn}
                options={[
                  { value: "plan", label: "Plan" },
                  { value: "last_used", label: "Last used" },
                ]}
                onValueChange={setStartIn}
              />
            </SettingsCardRow>
            <SettingsCardRow
              label="Messaging"
              description="Queue holds messages until the turn ends. Steer applies them mid-turn."
            >
              <div className="flex items-center gap-5">
                <div className="flex flex-col items-start gap-1">
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
                    Local
                  </span>
                  <SettingsSegmented
                    ariaLabel="Local messaging mode"
                    value={localMode}
                    options={[
                      { value: "queue", label: "Queue" },
                      { value: "steer", label: "Steer" },
                    ]}
                    onValueChange={setLocalMode}
                  />
                </div>
                <div className="flex flex-col items-start gap-1">
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
                    Cloud
                  </span>
                  <SettingsSegmented
                    ariaLabel="Cloud messaging mode"
                    value={cloudMode}
                    options={[
                      { value: "queue", label: "Queue" },
                      { value: "steer", label: "Steer" },
                    ]}
                    onValueChange={setCloudMode}
                  />
                </div>
              </div>
            </SettingsCardRow>
          </SettingsCard>
        </SettingsSection>

        <SettingsSection label="Composer">
          <SettingsCard>
            <SettingsCardRow
              label="Send messages with"
              description="Shift+Enter inserts a new line"
            >
              <SettingsSegmented
                ariaLabel="Send messages with"
                value={sendWith}
                options={[
                  { value: "enter", label: "Enter" },
                  { value: "cmd+enter", label: "⌘ Enter" },
                ]}
                onValueChange={setSendWith}
              />
            </SettingsCardRow>
            <SettingsCardRow
              label="Convert long pastes to attachments"
              description="Pasted text over this length becomes an attachment"
            >
              <SettingsSelect
                ariaLabel="Convert long pastes to attachments"
                value={convert}
                options={[
                  { value: "off", label: "Off" },
                  { value: "1000", label: "1,000 characters" },
                  { value: "2500", label: "2,500 characters" },
                ]}
                onChange={(v) => v && setConvert(v)}
                triggerClassName="w-[160px]"
              />
            </SettingsCardRow>
            <SettingsCardRow
              label="Keep awake while agents work"
              description="Stops your computer from sleeping on its own during a task"
            >
              <Switch
                size="sm"
                checked={keepAwake}
                onCheckedChange={setKeepAwake}
              />
            </SettingsCardRow>
          </SettingsCard>
        </SettingsSection>

        <SettingsSection label="Updates">
          <SettingsCard>
            <SettingsCardRow
              label={
                <span className="inline-flex items-baseline gap-2">
                  Version
                  <span className="font-mono font-normal text-[12px] text-muted-foreground">
                    0.61.61
                  </span>
                </span>
              }
              description="You're on the latest version"
            >
              <div className="flex items-center gap-2">
                <Button type="button" variant="link-muted" size="sm">
                  Changelog
                </Button>
                <Button type="button" variant="outline" size="sm">
                  Check now
                </Button>
              </div>
            </SettingsCardRow>
          </SettingsCard>
        </SettingsSection>
      </div>
    );
  },
};

export const NotificationDeliveryCards: Story = {
  render: function NotificationDeliveryCardsStory() {
    const [push, setPush] = useState(true);
    const [toast, setToast] = useState(true);
    const [badge, setBadge] = useState(true);
    const [bounce, setBounce] = useState(false);

    return (
      <SettingsSection
        label="Alerts"
        description="How agents get your attention when they finish or need you."
        action={
          <Button type="button" variant="link-muted" size="sm">
            Reset to defaults
          </Button>
        }
      >
        <div className="grid grid-cols-2 gap-2">
          <NotificationDeliveryCard
            title="System notifications"
            caption="When the app is in the background"
            illustration="push"
            checked={push}
            onCheckedChange={setPush}
          />
          <NotificationDeliveryCard
            title="In-app toasts"
            caption="While you're elsewhere in the app"
            illustration="toast"
            checked={toast}
            onCheckedChange={setToast}
          />
          <NotificationDeliveryCard
            title="Dock badge"
            caption="Unread dot on the app icon"
            illustration="dock-badge"
            checked={badge}
            onCheckedChange={setBadge}
          />
          <NotificationDeliveryCard
            title="Dock bounce"
            caption="Bounce the app icon once"
            illustration="dock-bounce"
            checked={bounce}
            onCheckedChange={setBounce}
          />
        </div>
      </SettingsSection>
    );
  },
};
