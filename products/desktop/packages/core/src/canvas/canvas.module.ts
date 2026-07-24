import { ContainerModule } from "inversify";
import { CanvasDataService } from "./canvasDataService";
import { CanvasTemplatesService } from "./canvasTemplatesService";
import { ChannelTasksService } from "./channelTasksService";
import { DashboardsService } from "./dashboardsService";
import { DESKTOP_FS_CLIENT, DesktopFsClient } from "./desktopFsClient";
import {
  CANVAS_DATA_SERVICE,
  CANVAS_TEMPLATES_SERVICE,
  CHANNEL_TASKS_SERVICE,
  DASHBOARDS_SERVICE,
} from "./identifiers";

// Host-agnostic canvas services (dashboards + freeform canvas data). They only
// need AuthService + fetch, so they live in @posthog/core and any host (desktop,
// web, server) can bind them by loading this module.
export const canvasCoreModule = new ContainerModule(({ bind }) => {
  bind(DesktopFsClient).toSelf().inSingletonScope();
  bind(DESKTOP_FS_CLIENT).toService(DesktopFsClient);

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
