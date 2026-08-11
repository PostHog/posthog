import { ContainerModule } from "inversify";
import { CanvasApplicationService } from "./canvasApplicationService";
import { CanvasDataService } from "./canvasDataService";
import { CanvasTemplatesService } from "./canvasTemplatesService";
import { ChannelTasksService } from "./channelTasksService";
import { DashboardsService } from "./dashboardsService";
import {
  CANVAS_APPLICATION_SERVICE,
  CANVAS_DATA_SERVICE,
  CANVAS_TEMPLATES_SERVICE,
  CHANNEL_TASKS_SERVICE,
  DASHBOARDS_SERVICE,
} from "./identifiers";
import { PROJECT_API_CLIENT, ProjectApiClient } from "./projectApiClient";

// Host-agnostic canvas services (dashboards + freeform canvas data). They only
// need AuthService + fetch, so they live in @posthog/core and any host (desktop,
// web, server) can bind them by loading this module.
export const canvasCoreModule = new ContainerModule(({ bind }) => {
  bind(ProjectApiClient).toSelf().inSingletonScope();
  bind(PROJECT_API_CLIENT).toService(ProjectApiClient);

  bind(CanvasDataService).toSelf().inSingletonScope();
  bind(CANVAS_DATA_SERVICE).toService(CanvasDataService);

  bind(DashboardsService).toSelf().inSingletonScope();
  bind(DASHBOARDS_SERVICE).toService(DashboardsService);

  bind(ChannelTasksService).toSelf().inSingletonScope();
  bind(CHANNEL_TASKS_SERVICE).toService(ChannelTasksService);

  // Canvas templates: host-agnostic (pure prompt strings), no deps. The
  // host-router canvas-templates router resolves it by token.
  bind(CanvasTemplatesService).toSelf().inSingletonScope();
  bind(CANVAS_TEMPLATES_SERVICE).toService(CanvasTemplatesService);
});

// Canvas generation orchestration. Bound separately from canvasCoreModule
// because it runs where tasks are created (the desktop renderer / web app
// container, which bind TASK_SERVICE and the model/title helpers), while
// canvasCoreModule's persistence services run host-side behind tRPC.
export const canvasApplicationModule = new ContainerModule(({ bind }) => {
  bind(CanvasApplicationService).toSelf().inSingletonScope();
  bind(CANVAS_APPLICATION_SERVICE).toService(CanvasApplicationService);
});
