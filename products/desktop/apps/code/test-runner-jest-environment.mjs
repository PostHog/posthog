import path from "node:path";
import { fileURLToPath } from "node:url";
import BaseEnvironment from "@storybook/test-runner/playwright/custom-environment.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FAILURES_DIR = path.join(
  __dirname,
  ".storybook",
  "__snapshots__",
  "__failures__",
);

/** Captures a full-page screenshot when a story test fails, for CI artifact upload. */
class CustomEnvironment extends BaseEnvironment {
  async handleTestEvent(event, state) {
    if (event.name === "test_done" && event.test.errors.length > 0) {
      const parentName = event.test.parent.name
        .replace(/\W+/g, "-")
        .toLowerCase();
      const specName = event.test.name.replace(/\W+/g, "-").toLowerCase();
      await this.global.page
        .screenshot({
          path: path.join(FAILURES_DIR, `${parentName}--${specName}.png`),
          timeout: 5000,
        })
        .catch(() => undefined);
    }
    await super.handleTestEvent(event, state);
  }
}

export default CustomEnvironment;
