import { z } from "zod";
import { container } from "../../di/container";
import { WORKSPACE_SERVER_SERVICE } from "../../di/tokens";
import {
  WorkspaceServerEvent,
  type WorkspaceServerService,
} from "../../services/workspace-server/service";
import { publicProcedure, router } from "../trpc";

const connectionSchema = z.object({
  url: z.string().url(),
  secret: z.string().min(1),
});

const getService = () =>
  container.get<WorkspaceServerService>(WORKSPACE_SERVER_SERVICE);

export const workspaceServerRouter = router({
  getConnection: publicProcedure.output(connectionSchema).query(async () => {
    const service = getService();
    return service.getConnection() ?? service.start();
  }),

  restart: publicProcedure.mutation(async () => {
    await getService().restart();
  }),

  onConnectionLost: publicProcedure.subscription(async function* (opts) {
    const service = getService();
    const iterable = service.toIterable(WorkspaceServerEvent.ConnectionLost, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  onStatusChanged: publicProcedure.subscription(async function* (opts) {
    const service = getService();
    const iterable = service.toIterable(WorkspaceServerEvent.StatusChanged, {
      signal: opts.signal,
    });
    // toIterable attaches its listener on the first pull. Prime it before
    // reading the snapshot so a transition in between is buffered, not dropped.
    const firstEvent = iterable.next();
    yield service.getStatusSnapshot();
    try {
      let result = await firstEvent;
      while (!result.done) {
        yield result.value;
        result = await iterable.next();
      }
    } finally {
      await iterable.return?.(undefined);
    }
  }),
});
