import type { Contribution } from "@posthog/di/contribution";
import { inject, injectable } from "inversify";
import type { AutoresearchService } from "./autoresearch";
import { AUTORESEARCH_SERVICE } from "./identifiers";

/**
 * Restores persisted autoresearch runs at boot so runs that were mid-loop
 * when the app quit come back as interrupted and re-enter recovery instead
 * of vanishing. Fire-and-forget: boot() runs contributions serially and a
 * storage read must not delay it.
 */
@injectable()
export class AutoresearchRehydrationContribution implements Contribution {
  constructor(
    @inject(AUTORESEARCH_SERVICE)
    private readonly autoresearch: AutoresearchService,
  ) {}

  start(): void {
    void this.autoresearch.rehydrate();
  }
}
