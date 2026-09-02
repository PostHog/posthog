import { inject, injectable } from "inversify";
import {
  CLOUD_TASK_CLIENT,
  type CloudTaskClient,
} from "../cloud-task/cloudTaskClient";
import { TASK_SERVICE, type TaskService } from "../task-detail/taskService";
import {
  CloudPiSessionClient,
  type CloudPiSessionContext,
} from "./cloudPiSessionClient";
import {
  LOCAL_PI_SESSION_FACTORY,
  type PiSession,
  type PiSessionFactory,
  type PiSessionProvider,
} from "./piSessionController";

@injectable()
export class RoutingPiSessionProvider implements PiSessionProvider {
  constructor(
    @inject(LOCAL_PI_SESSION_FACTORY)
    private readonly localFactory: PiSessionFactory,
    @inject(CLOUD_TASK_CLIENT)
    private readonly cloudTaskClient: CloudTaskClient,
    @inject(TASK_SERVICE)
    private readonly taskService: TaskService,
  ) {}

  async get(taskId: string, taskRunId?: string): Promise<PiSession> {
    const cloudContext = await this.resolveCloudContext(taskId, taskRunId);
    if (cloudContext) {
      return new CloudPiSessionClient(this.cloudTaskClient, cloudContext);
    }
    return this.localFactory.get(taskId);
  }

  private async resolveCloudContext(
    taskId: string,
    taskRunId?: string,
  ): Promise<CloudPiSessionContext | null> {
    const [task, context] = await Promise.all([
      this.taskService.getTask(taskId, taskRunId),
      this.cloudTaskClient.getContext(),
    ]);
    const run = task.latest_run;
    if (!context || !run || run.environment !== "cloud") {
      return null;
    }

    const storage = await this.taskService
      .getCloudPiTaskSessionStorage(taskId, run.id)
      .catch(() => null);
    const persistedConfig =
      storage?.download_url && this.localFactory.readSessionConfig
        ? await this.localFactory
            .readSessionConfig(storage.download_url)
            .catch(() => null)
        : null;

    return {
      taskId,
      runId: run.id,
      runStatus: run.status,
      persistedConfig,
      ...context,
    };
  }
}
