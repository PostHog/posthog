// DI tokens for the canvas/dashboards services. They live in @posthog/core so
// both the host-router routers and the host DI container can reference them
// without depending on the desktop app's main process (where the concrete
// service classes are bound).
export const CANVAS_TEMPLATES_SERVICE = Symbol.for(
  "posthog.core.canvas.templatesService",
);
export const DASHBOARDS_SERVICE = Symbol.for(
  "posthog.core.canvas.dashboardsService",
);
export const CANVAS_DATA_SERVICE = Symbol.for(
  "posthog.core.canvas.dataService",
);
export const CHANNEL_TASKS_SERVICE = Symbol.for(
  "posthog.core.canvas.channelTasksService",
);
