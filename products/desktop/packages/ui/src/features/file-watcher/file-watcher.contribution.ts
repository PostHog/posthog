import type { Contribution } from "@posthog/di/contribution";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { inject, injectable } from "inversify";

@injectable()
export class FileWatcherContribution implements Contribution {
  constructor(
    @inject(ROOT_LOGGER)
    private readonly logger: RootLogger,
  ) {}

  start(): void {
    this.logger.info("file-watcher feature ready");
  }
}
