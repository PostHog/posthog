import type { HedgehogActorOptions } from "@posthog/hedgehog-mode";
import type {
  HedgehogModeHandle,
  HedgehogModeHost,
  HedgehogModeMountOptions,
} from "@posthog/ui/shell/hedgehogModeHost";

export class RendererHedgehogModeHost implements HedgehogModeHost {
  async mount(
    container: HTMLDivElement,
    options: HedgehogModeMountOptions,
  ): Promise<HedgehogModeHandle> {
    const { HedgeHogMode } = await import("@posthog/hedgehog-mode");
    const actorOptions = options.actorOptions as
      | HedgehogActorOptions
      | undefined;

    const game = new HedgeHogMode({
      assetsUrl: "./hedgehog-mode",
      state: actorOptions ? { options: actorOptions } : undefined,
      onQuit: (g) => {
        g.getAllHedgehogs().forEach((hedgehog) => {
          hedgehog.updateSprite("wave", { reset: true, loop: false });
        });
        setTimeout(() => options.onQuit(), 1000);
      },
    });

    await game.render(container);

    const canvas = game.app.canvas;
    const notifyContextLost = () => options.onContextLost?.();
    canvas.addEventListener("webglcontextlost", notifyContextLost, {
      once: true,
    });

    return {
      destroy: () => {
        canvas.removeEventListener("webglcontextlost", notifyContextLost);
        // HedgeHogMode.destroy() tears down the Pixi app but never visits
        // `elements`, so actor AI timers, per-actor input listeners and
        // module-level spawn counters survive it and pin the dead game in
        // memory. Drain the elements first: removeElement runs each
        // element's beforeUnload, and destroying the sprite releases its
        // shared-ticker registration, which stage removal alone does not.
        for (const element of [...game.elements]) {
          try {
            game.removeElement(element);
            element.sprite?.destroy({ children: true });
          } catch {
            // One broken element must not stop the rest of the drain.
          }
        }
        game.destroy();
      },
      isContextLost: () => {
        const renderer = game.app.renderer as unknown as {
          context?: { isLost?: boolean };
        };
        return renderer.context?.isLost === true;
      },
    };
  }
}
