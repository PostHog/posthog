import {
  CanvasLinkEvent,
  type CanvasLinkPayload,
  type CanvasLinkService,
} from "@posthog/core/links/canvas-link";
import {
  ChannelLinkEvent,
  type ChannelLinkPayload,
  type ChannelLinkService,
} from "@posthog/core/links/channel-link";
import {
  CANVAS_LINK_SERVICE,
  CHANNEL_LINK_SERVICE,
  INBOX_LINK_SERVICE,
  LOOP_LINK_SERVICE,
  NEW_TASK_LINK_SERVICE,
  OPEN_TARGET_LINK_SERVICE,
  SCOUT_LINK_SERVICE,
  TASK_LINK_SERVICE,
} from "@posthog/core/links/identifiers";
import {
  InboxLinkEvent,
  type InboxLinkService,
  type PendingInboxDeepLink,
} from "@posthog/core/links/inbox-link";
import {
  LoopLinkEvent,
  type LoopLinkPayload,
  type LoopLinkService,
} from "@posthog/core/links/loop-link";
import {
  NewTaskLinkEvent,
  type NewTaskLinkPayload,
  type NewTaskLinkService,
} from "@posthog/core/links/new-task-link";
import {
  OpenTargetLinkEvent,
  type OpenTargetLinkService,
} from "@posthog/core/links/open-target-link";
import {
  ScoutLinkEvent,
  type ScoutLinkPayload,
  type ScoutLinkService,
} from "@posthog/core/links/scout-link";
import {
  type PendingDeepLink,
  TaskLinkEvent,
  type TaskLinkService,
} from "@posthog/core/links/task-link";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  DEEP_LINK_SERVICE,
  type IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import type { NotificationTarget } from "@posthog/platform/notifications";
import { buildActionUrl, openAgentActionInput } from "@posthog/shared";
import { z } from "zod";

export const deepLinkRouter = router({
  // In-app surfaces (announcement CTAs) dispatch posthog-code:// urls through
  // the same main-process handler OS-delivered links use — no OS round-trip,
  // no browser bounce, and dev builds (posthog-code-dev scheme) stay in-app.
  open: publicProcedure
    .input(z.object({ url: z.string() }))
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IDeepLinkRegistry>(DEEP_LINK_SERVICE)
        .handleUrl(input.url),
    ),

  // A typed verb rather than a url, unlike `open` above: the agent names the
  // action and the host builds the link, so nothing an agent writes decides
  // where a click lands.
  openAgentAction: publicProcedure
    .input(openAgentActionInput)
    .mutation(({ ctx, input }) => {
      const deepLinks = ctx.container.get<IDeepLinkRegistry>(DEEP_LINK_SERVICE);
      return deepLinks.handleUrl(
        buildActionUrl(input.action, deepLinks.getProtocol()),
      );
    }),

  onOpenTask: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<TaskLinkService>(TASK_LINK_SERVICE);
    const iterable = service.toIterable(TaskLinkEvent.OpenTask, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  getPendingDeepLink: publicProcedure.query(
    ({ ctx }): PendingDeepLink | null => {
      return ctx.container
        .get<TaskLinkService>(TASK_LINK_SERVICE)
        .consumePendingDeepLink();
    },
  ),

  onOpenReport: publicProcedure.subscription(async function* (opts) {
    const service =
      opts.ctx.container.get<InboxLinkService>(INBOX_LINK_SERVICE);
    const iterable = service.toIterable(InboxLinkEvent.OpenReport, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  getPendingReportLink: publicProcedure.query(
    ({ ctx }): PendingInboxDeepLink | null => {
      return ctx.container
        .get<InboxLinkService>(INBOX_LINK_SERVICE)
        .consumePendingDeepLink();
    },
  ),

  onOpenScout: publicProcedure.subscription(async function* (opts) {
    const service =
      opts.ctx.container.get<ScoutLinkService>(SCOUT_LINK_SERVICE);
    const iterable = service.toIterable(ScoutLinkEvent.OpenScout, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  getPendingScoutLink: publicProcedure.query(
    ({ ctx }): ScoutLinkPayload | null => {
      return ctx.container
        .get<ScoutLinkService>(SCOUT_LINK_SERVICE)
        .consumePendingDeepLink();
    },
  ),

  onNewTaskAction: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<NewTaskLinkService>(
      NEW_TASK_LINK_SERVICE,
    );
    const iterable = service.toIterable(NewTaskLinkEvent.Action, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  getPendingNewTaskLink: publicProcedure.query(
    ({ ctx }): NewTaskLinkPayload | null => {
      return ctx.container
        .get<NewTaskLinkService>(NEW_TASK_LINK_SERVICE)
        .consumePendingLink();
    },
  ),

  // Generic "open this target" intents from clicked native notifications. The
  // renderer subscribes and navigates by target kind (task / canvas / …).
  onOpenTarget: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<OpenTargetLinkService>(
      OPEN_TARGET_LINK_SERVICE,
    );
    const iterable = service.toIterable(OpenTargetLinkEvent.Open, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  getPendingOpenTarget: publicProcedure.query(
    ({ ctx }): NotificationTarget | null => {
      return ctx.container
        .get<OpenTargetLinkService>(OPEN_TARGET_LINK_SERVICE)
        .consumePending();
    },
  ),

  onOpenCanvas: publicProcedure.subscription(async function* (opts) {
    const service =
      opts.ctx.container.get<CanvasLinkService>(CANVAS_LINK_SERVICE);
    const iterable = service.toIterable(CanvasLinkEvent.OpenCanvas, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  getPendingCanvasLink: publicProcedure.query(
    ({ ctx }): CanvasLinkPayload | null => {
      return ctx.container
        .get<CanvasLinkService>(CANVAS_LINK_SERVICE)
        .consumePendingDeepLink();
    },
  ),

  onOpenChannel: publicProcedure.subscription(async function* (opts) {
    const service =
      opts.ctx.container.get<ChannelLinkService>(CHANNEL_LINK_SERVICE);
    const iterable = service.toIterable(ChannelLinkEvent.OpenChannel, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  getPendingChannelLink: publicProcedure.query(
    ({ ctx }): ChannelLinkPayload | null => {
      return ctx.container
        .get<ChannelLinkService>(CHANNEL_LINK_SERVICE)
        .consumePendingDeepLink();
    },
  ),

  onOpenLoop: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<LoopLinkService>(LOOP_LINK_SERVICE);
    const iterable = service.toIterable(LoopLinkEvent.OpenLoop, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  getPendingLoopLink: publicProcedure.query(
    ({ ctx }): LoopLinkPayload | null => {
      return ctx.container
        .get<LoopLinkService>(LOOP_LINK_SERVICE)
        .consumePendingDeepLink();
    },
  ),
});
