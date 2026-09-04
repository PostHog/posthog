import {
  CalendarBlankIcon,
  ChartBarIcon,
  ChartLineIcon,
  FrameCornersIcon,
  GaugeIcon,
  type Icon,
  LayoutIcon,
  LightbulbIcon,
  ListChecksIcon,
  NoteIcon,
  NotePencilIcon,
  PresentationIcon,
  SquaresFourIcon,
  TableIcon,
  TextAaIcon,
  TextAlignLeftIcon,
} from "@phosphor-icons/react";

const ENTRY_ICON: Record<string, Icon> = {
  sticky: NoteIcon,
  text: TextAlignLeftIcon,
  heading: TextAaIcon,
  "date-range": CalendarBlankIcon,
  kpi: GaugeIcon,
  "trend-chart": ChartLineIcon,
  "bar-chart": ChartBarIcon,
  insight: LightbulbIcon,
  "sql-table": TableIcon,
  checklist: ListChecksIcon,
  notes: NotePencilIcon,
  layout: LayoutIcon,
  "date-frame": FrameCornersIcon,
  slideshow: PresentationIcon,
};

export function libraryEntryIcon(name: string): Icon {
  return ENTRY_ICON[name] ?? SquaresFourIcon;
}
