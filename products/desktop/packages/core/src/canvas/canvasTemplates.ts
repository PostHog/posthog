import { FREEFORM_TEMPLATE_ID } from "./freeformSchemas";
import type { CanvasTemplateSummary } from "./templateSchemas";

const FREEFORM_SUGGESTIONS = [
  {
    label: "Signups chart",
    prompt:
      "Build an app that shows daily new signups for the last 30 days as a line chart, with a total at the top.",
  },
  {
    label: "Top events",
    prompt:
      "Build an app listing the top 10 events by volume in the last 7 days, with a bar chart and a refresh button.",
  },
  {
    label: "Metric explorer",
    prompt:
      "Build a small tool with a dropdown to pick an event and a chart that shows its daily count over the last 14 days.",
  },
];

const FREEFORM_TEMPLATE: CanvasTemplateSummary = {
  id: FREEFORM_TEMPLATE_ID,
  name: "Freeform (React)",
  description:
    "Describe anything. The agent writes a React app that runs in a sandbox and can be shared.",
  builtIn: true,
  suggestions: FREEFORM_SUGGESTIONS,
};

export const BUILT_IN_TEMPLATES: CanvasTemplateSummary[] = [FREEFORM_TEMPLATE];

export const DEFAULT_TEMPLATE_ID = FREEFORM_TEMPLATE_ID;
