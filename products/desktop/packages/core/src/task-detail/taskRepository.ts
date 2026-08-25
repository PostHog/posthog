import type { SagaLogger, TaskCreationInput } from "@posthog/shared";
import type { ITaskCreationHost } from "./taskCreationHost";

export async function resolveTaskRepository(
  input: TaskCreationInput,
  host: Pick<ITaskCreationHost, "detectRepo">,
  logger: Pick<SagaLogger, "warn">,
): Promise<string | undefined> {
  if (input.repository) {
    return input.repository;
  }
  if (!input.repoPath) {
    return undefined;
  }

  try {
    const detected = await host.detectRepo({ directoryPath: input.repoPath });
    if (!detected) {
      return undefined;
    }
    return `${detected.organization}/${detected.repository}`;
  } catch (error) {
    logger.warn("Repo detection failed; creating task without one", { error });
    return undefined;
  }
}
