import {
  ArchiveIcon,
  BellIcon,
  BookOpenTextIcon,
  BrainIcon,
  GearIcon,
  PlugsConnectedIcon,
  RepeatIcon,
  RobotIcon,
  SquaresFourIcon,
  TrayIcon,
} from "@phosphor-icons/react";
import type { AppViewType } from "@posthog/ui/router/useAppView";
import type { ReactNode } from "react";

export type TabAppView = Extract<
  AppViewType,
  | "activity"
  | "home"
  | "inbox"
  | "agents"
  | "loops"
  | "archived"
  | "command-center"
  | "context"
  | "skills"
  | "mcp-servers"
  | "settings"
>;

export const TAB_APP_VIEW_META: Record<
  TabAppView,
  { label: string; icon: ReactNode }
> = {
  activity: {
    label: "Activity",
    icon: <BellIcon size={14} />,
  },
  home: { label: "Home", icon: <SquaresFourIcon size={14} /> },
  inbox: { label: "Self-driving", icon: <TrayIcon size={14} /> },
  agents: { label: "Agents", icon: <RobotIcon size={14} /> },
  loops: { label: "Loops", icon: <RepeatIcon size={14} /> },
  archived: { label: "Archived", icon: <ArchiveIcon size={14} /> },
  skills: { label: "Skills", icon: <BrainIcon size={14} /> },
  "mcp-servers": {
    label: "MCP servers",
    icon: <PlugsConnectedIcon size={14} />,
  },
  "command-center": {
    label: "Command center",
    icon: <SquaresFourIcon size={14} />,
  },
  context: { label: "Context", icon: <BookOpenTextIcon size={14} /> },
  settings: { label: "Settings", icon: <GearIcon size={14} /> },
};

export function isTabAppView(value: string): value is TabAppView {
  return Object.hasOwn(TAB_APP_VIEW_META, value);
}
