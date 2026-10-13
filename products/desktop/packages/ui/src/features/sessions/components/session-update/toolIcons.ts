import {
  ArrowsClockwise,
  ArrowsLeftRight,
  Brain,
  ChatCircle,
  FileText,
  FolderSimple,
  Globe,
  type Icon,
  MagnifyingGlass,
  PencilSimple,
  Terminal,
  Trash,
  Wrench,
} from "@phosphor-icons/react";
import type { CodeToolKind } from "../../types";

const TOOL_KIND_ICONS: Record<CodeToolKind, Icon> = {
  read: FileText,
  list: FolderSimple,
  edit: PencilSimple,
  delete: Trash,
  move: ArrowsLeftRight,
  search: MagnifyingGlass,
  execute: Terminal,
  think: Brain,
  fetch: Globe,
  switch_mode: ArrowsClockwise,
  question: ChatCircle,
  other: Wrench,
};

export function iconForToolKind(kind: CodeToolKind | null | undefined): Icon {
  return (kind && TOOL_KIND_ICONS[kind]) || Wrench;
}
