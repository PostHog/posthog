import {
  BugIcon,
  ChartBarIcon,
  ChatsCircleIcon,
  CursorClickIcon,
  FlagIcon,
  FlaskIcon,
  LightningIcon,
  LinkIcon,
  NotebookIcon,
  PlayCircleIcon,
  SquaresFourIcon,
  UserIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import type { ContextObjectKind } from "@posthog/core/canvas/contextDocument";
import type { ReactNode } from "react";

export const KIND_ICONS: Record<ContextObjectKind, ReactNode> = {
  insight: <ChartBarIcon size={15} />,
  dashboard: <SquaresFourIcon size={15} />,
  flag: <FlagIcon size={15} />,
  experiment: <FlaskIcon size={15} />,
  survey: <ChatsCircleIcon size={15} />,
  error: <BugIcon size={15} />,
  replay: <PlayCircleIcon size={15} />,
  notebook: <NotebookIcon size={15} />,
  cohort: <UsersThreeIcon size={15} />,
  action: <CursorClickIcon size={15} />,
  person: <UserIcon size={15} />,
  event: <LightningIcon size={15} />,
  link: <LinkIcon size={15} />,
};
