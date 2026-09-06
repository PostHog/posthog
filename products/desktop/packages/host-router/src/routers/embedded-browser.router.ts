import type { IEmbeddedBrowserService } from "@posthog/core/embedded-browser/embeddedBrowser";
import { EMBEDDED_BROWSER_SERVICE } from "@posthog/core/embedded-browser/identifiers";
import {
  embeddedBrowserPageStateSchema,
  embeddedBrowserViewIdInput,
  navigateEmbeddedBrowserInput,
  openEmbeddedBrowserInput,
  setEmbeddedBrowserBoundsInput,
  setEmbeddedBrowserVisibleInput,
} from "@posthog/core/embedded-browser/schemas";
import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";

const svc = (container: ServiceResolver) =>
  container.get<IEmbeddedBrowserService>(EMBEDDED_BROWSER_SERVICE);

export const embeddedBrowserRouter = router({
  open: publicProcedure
    .input(openEmbeddedBrowserInput)
    .mutation(({ ctx, input }) => svc(ctx.container).open(input)),

  navigate: publicProcedure
    .input(navigateEmbeddedBrowserInput)
    .mutation(({ ctx, input }) =>
      svc(ctx.container).navigate(input.viewId, input.url),
    ),

  goBack: publicProcedure
    .input(embeddedBrowserViewIdInput)
    .mutation(({ ctx, input }) => svc(ctx.container).goBack(input.viewId)),

  goForward: publicProcedure
    .input(embeddedBrowserViewIdInput)
    .mutation(({ ctx, input }) => svc(ctx.container).goForward(input.viewId)),

  reload: publicProcedure
    .input(embeddedBrowserViewIdInput)
    .mutation(({ ctx, input }) => svc(ctx.container).reload(input.viewId)),

  setBounds: publicProcedure
    .input(setEmbeddedBrowserBoundsInput)
    .mutation(({ ctx, input }) =>
      svc(ctx.container).setBounds(input.viewId, input.bounds),
    ),

  setVisible: publicProcedure
    .input(setEmbeddedBrowserVisibleInput)
    .mutation(({ ctx, input }) =>
      svc(ctx.container).setVisible(input.viewId, input.visible),
    ),

  openDevTools: publicProcedure
    .input(embeddedBrowserViewIdInput)
    .mutation(({ ctx, input }) =>
      svc(ctx.container).openDevTools(input.viewId),
    ),

  destroy: publicProcedure
    .input(embeddedBrowserViewIdInput)
    .mutation(({ ctx, input }) => svc(ctx.container).destroy(input.viewId)),

  getPageState: publicProcedure
    .input(embeddedBrowserViewIdInput)
    .output(embeddedBrowserPageStateSchema.nullable())
    .query(({ ctx, input }) => svc(ctx.container).getPageState(input.viewId)),

  onEvents: publicProcedure.subscription(async function* (opts) {
    for await (const event of svc(opts.ctx.container).events(opts.signal)) {
      yield event;
    }
  }),
});
