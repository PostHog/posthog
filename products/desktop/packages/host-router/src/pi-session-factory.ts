import {
  getRemotePiConversation,
  RemotePiRpcClient,
} from "@posthog/agent/pi/remote-rpc-client";
import type {
  PiSession,
  PiSessionFactory,
} from "@posthog/core/pi-runtime/piSessionController";
import { inject, injectable } from "inversify";
import type { HostTrpcClient } from "./client";
import { HOST_TRPC_CLIENT } from "./client";

class TrpcPiSession implements PiSession {
  readonly client: RemotePiRpcClient;

  constructor(
    private readonly hostClient: HostTrpcClient,
    private readonly taskId: string,
  ) {
    this.client = new RemotePiRpcClient({
      request: async (command) => {
        const response = await this.hostClient.piSession.rpc.mutate({
          taskId: this.taskId,
          command,
        });
        return response;
      },
    });
  }

  health() {
    return this.hostClient.piSession.health.query({ taskId: this.taskId });
  }

  getConversation() {
    return getRemotePiConversation(this.client);
  }

  getQueue() {
    return this.hostClient.piSession.getQueue.query({ taskId: this.taskId });
  }

  clearQueue() {
    return this.hostClient.piSession.clearQueue.mutate({ taskId: this.taskId });
  }

  onMcpToolPermissionRequest(
    onRequest: Parameters<
      NonNullable<PiSession["onMcpToolPermissionRequest"]>
    >[0],
    onError: Parameters<
      NonNullable<PiSession["onMcpToolPermissionRequest"]>
    >[1],
  ): () => void {
    const subscription =
      this.hostClient.piSession.onMcpToolPermissionRequest.subscribe(
        { taskId: this.taskId },
        { onData: onRequest, onError },
      );
    return () => subscription.unsubscribe();
  }

  respondMcpToolPermission(
    request: Parameters<NonNullable<PiSession["respondMcpToolPermission"]>>[0],
    decision: Parameters<NonNullable<PiSession["respondMcpToolPermission"]>>[1],
  ): Promise<void> {
    return this.hostClient.piSession.respondMcpToolPermission.mutate({
      taskId: this.taskId,
      request,
      decision,
    });
  }

  respondToExtensionUI(
    response: Parameters<NonNullable<PiSession["respondToExtensionUI"]>>[0],
  ) {
    return this.hostClient.piSession.respondToExtensionUI.mutate({
      taskId: this.taskId,
      response,
    });
  }

  onExtensionEvent(
    onEvent: Parameters<NonNullable<PiSession["onExtensionEvent"]>>[0],
    onError: Parameters<NonNullable<PiSession["onExtensionEvent"]>>[1],
    onComplete?: Parameters<NonNullable<PiSession["onExtensionEvent"]>>[2],
  ): () => void {
    const subscription = this.hostClient.piSession.onExtensionEvent.subscribe(
      { taskId: this.taskId },
      {
        onData: onEvent,
        onError,
        onComplete,
      },
    );

    return () => subscription.unsubscribe();
  }

  onConversationEvent(
    onEvent: Parameters<PiSession["onConversationEvent"]>[0],
    onError: Parameters<PiSession["onConversationEvent"]>[1],
  ): () => void {
    const subscription = this.hostClient.piSession.onEvent.subscribe(
      { taskId: this.taskId },
      { onData: (event) => onEvent(event, { isLive: true }), onError },
    );

    return () => subscription.unsubscribe();
  }
}

@injectable()
export class TrpcPiSessionFactory implements PiSessionFactory {
  constructor(
    @inject(HOST_TRPC_CLIENT) private readonly client: HostTrpcClient,
  ) {}

  get(taskId: string): Promise<PiSession> {
    return Promise.resolve(new TrpcPiSession(this.client, taskId));
  }

  readSessionConfig(downloadUrl: string) {
    return this.client.piSession.readSessionConfig.query({ downloadUrl });
  }
}
