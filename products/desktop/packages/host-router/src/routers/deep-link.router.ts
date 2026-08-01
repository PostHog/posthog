import {
  ApprovalLinkEvent,
  type ApprovalLinkPayload,
  type ApprovalLinkService,
} from "@posthog/core/links/approval-link";
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
  APPROVAL_LINK_SERVICE,
  CANVAS_LINK_SERVICE,
  CHANNEL_LINK_SERVICE,
  INBOX_LINK_SERVICE,
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
import type { NotificationTarget } from "@posthog/platform/notifications";

export const deepLinkRouter = router({
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

  onOpenApproval: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<ApprovalLinkService>(
      APPROVAL_LINK_SERVICE,
    );
    const iterable = service.toIterable(ApprovalLinkEvent.OpenApproval, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  getPendingApprovalLink: publicProcedure.query(
    ({ ctx }): ApprovalLinkPayload | null => {
      return ctx.container
        .get<ApprovalLinkService>(APPROVAL_LINK_SERVICE)
        .consumePendingDeepLink();
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
});
