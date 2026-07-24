import { type HostLogger, logger as uiLogger } from "@posthog/ui/shell/logger";
import log from "electron-log/renderer";

log.transports.console.level = "debug";

export const hostLog = log as unknown as HostLogger;

export const logger = uiLogger;
