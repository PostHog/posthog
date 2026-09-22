import {
  ChartBarIcon,
  ChartLineIcon,
  FileIcon,
  ShapesIcon,
} from "@phosphor-icons/react";
import { FREEFORM_TEMPLATE_ID } from "@posthog/core/canvas/freeformSchemas";
import type { ReactNode } from "react";

// A canvas's leading icon, chosen from its template so the tree and header read
// at a glance: shapes for a freeform canvas, plain file for a blank one, and
// line/bar charts for the legacy template ids older records still carry.
export function iconForTemplate(
  templateId: string,
  opts?: { size?: number; className?: string },
): ReactNode {
  const size = opts?.size ?? 16;
  const className = opts?.className ?? "text-gray-9";
  switch (templateId) {
    case "web-analytics":
      return <ChartLineIcon size={size} className={className} />;
    case "blank":
      return <FileIcon size={size} className={className} />;
    case FREEFORM_TEMPLATE_ID:
      return <ShapesIcon size={size} className={className} />;
    default:
      return <ChartBarIcon size={size} className={className} />;
  }
}
