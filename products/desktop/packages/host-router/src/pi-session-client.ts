import type { PiSessionClient } from "@posthog/core/pi-runtime/piSessionController";
import { inject, injectable } from "inversify";
import { HOST_TRPC_CLIENT, type HostTrpcClient } from "./client";

@injectable()
export class TrpcPiSessionClient implements PiSessionClient {
  constructor(
    @inject(HOST_TRPC_CLIENT) private readonly client: HostTrpcClient,
  ) {}

  health(taskId: string) {
    return this.client.piSession.health.query({ taskId });
  }

  conversation(taskId: string) {
    return this.client.piSession.conversation.query({ taskId });
  }

  status(taskId: string) {
    return this.client.piSession.status.query({ taskId });
  }

  availableModels(taskId: string) {
    return this.client.piSession.availableModels.query({ taskId });
  }

  commands(taskId: string) {
    return this.client.piSession.commands.query({ taskId });
  }

  subscribe(
    taskId: string,
    onEvent: Parameters<PiSessionClient["subscribe"]>[1],
    onError: Parameters<PiSessionClient["subscribe"]>[2],
  ): () => void {
    const subscription = this.client.piSession.onEvent.subscribe(
      { taskId },
      { onData: onEvent, onError },
    );

    return () => subscription.unsubscribe();
  }

  prompt(taskId: string, prompt: string) {
    return this.client.piSession.prompt.mutate({ taskId, prompt });
  }

  steer(taskId: string, message: string) {
    return this.client.piSession.steer.mutate({ taskId, message });
  }

  followUp(taskId: string, message: string) {
    return this.client.piSession.followUp.mutate({ taskId, message });
  }

  compact(taskId: string, customInstructions?: string) {
    return this.client.piSession.compact.mutate({ taskId, customInstructions });
  }

  setModel(taskId: string, provider: string, modelId: string) {
    return this.client.piSession.setModel.mutate({ taskId, provider, modelId });
  }

  setThinkingLevel(
    taskId: string,
    level: Parameters<PiSessionClient["setThinkingLevel"]>[1],
  ) {
    return this.client.piSession.setThinkingLevel.mutate({ taskId, level });
  }

  setSteeringMode(
    taskId: string,
    mode: Parameters<PiSessionClient["setSteeringMode"]>[1],
  ) {
    return this.client.piSession.setSteeringMode.mutate({ taskId, mode });
  }

  setFollowUpMode(
    taskId: string,
    mode: Parameters<PiSessionClient["setFollowUpMode"]>[1],
  ) {
    return this.client.piSession.setFollowUpMode.mutate({ taskId, mode });
  }

  bash(taskId: string, command: string) {
    return this.client.piSession.bash.mutate({ taskId, command });
  }

  abort(taskId: string) {
    return this.client.piSession.abort.mutate({ taskId });
  }

  abortBash(taskId: string) {
    return this.client.piSession.abortBash.mutate({ taskId });
  }
}
