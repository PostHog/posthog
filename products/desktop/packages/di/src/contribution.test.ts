import { Container } from "inversify";
import { describe, expect, it } from "vitest";
import { boot, CONTRIBUTION, type Contribution } from "./contribution";

describe("boot", () => {
  it("resolves nothing when no contribution is bound", async () => {
    const container = new Container();
    await expect(boot(container)).resolves.toBeUndefined();
  });

  it("starts every bound contribution in binding order", async () => {
    const started: string[] = [];
    const make = (name: string): Contribution => ({
      start() {
        started.push(name);
      },
    });

    const container = new Container();
    container.bind(CONTRIBUTION).toConstantValue(make("first"));
    container.bind(CONTRIBUTION).toConstantValue(make("second"));

    await boot(container);

    expect(started).toEqual(["first", "second"]);
  });

  it("awaits async contributions before resolving", async () => {
    const order: string[] = [];
    const slow: Contribution = {
      async start() {
        await Promise.resolve();
        order.push("slow-start-done");
      },
    };

    const container = new Container();
    container.bind(CONTRIBUTION).toConstantValue(slow);

    await boot(container);
    order.push("after-boot");

    expect(order).toEqual(["slow-start-done", "after-boot"]);
  });
});
