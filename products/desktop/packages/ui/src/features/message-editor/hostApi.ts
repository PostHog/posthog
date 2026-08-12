import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import type { HostRouter } from "@posthog/host-router/router";
import type { GithubRef } from "@posthog/shared";
import {
  createTRPCOptionsProxy,
  type TRPCOptionsProxy,
} from "@trpc/tanstack-react-query";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "../../shell/queryClient";
import type { GhStatus, SelectedAttachment } from "./identifiers";

function hostClient(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}

function imperativeQueryClient(): ImperativeQueryClient {
  return resolveService<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT);
}

let optionsProxy: TRPCOptionsProxy<HostRouter> | null = null;

function options(): TRPCOptionsProxy<HostRouter> {
  if (!optionsProxy) {
    optionsProxy = createTRPCOptionsProxy<HostRouter>({
      client: hostClient(),
      queryClient: imperativeQueryClient(),
    });
  }
  return optionsProxy;
}

export function searchGithubRefs(input: {
  directoryPath: string;
  query?: string;
  limit?: number;
}): Promise<GithubRef[]> {
  return imperativeQueryClient().fetchQuery({
    ...options().git.searchGithubRefs.queryOptions(input),
    staleTime: 30_000,
  });
}

export function getGithubPullRequest(input: {
  owner: string;
  repo: string;
  number: number;
}): Promise<GithubRef | null> {
  return imperativeQueryClient().fetchQuery({
    ...options().git.getGithubPullRequest.queryOptions(input),
    staleTime: 60_000,
  });
}

export function getGithubIssue(input: {
  owner: string;
  repo: string;
  number: number;
}): Promise<GithubRef | null> {
  return imperativeQueryClient().fetchQuery({
    ...options().git.getGithubIssue.queryOptions(input),
    staleTime: 60_000,
  });
}

export function getGhStatus(): Promise<GhStatus> {
  return hostClient().git.getGhStatus.query();
}

export function selectDirectory(): Promise<string | null> {
  return hostClient().os.selectDirectory.query();
}

export function selectAttachments(input: {
  mode: "files" | "directories" | "both";
}): Promise<SelectedAttachment[]> {
  return hostClient().os.selectAttachments.query(input);
}

export function readFileAsDataUrl(input: {
  filePath: string;
}): Promise<string | null> {
  return hostClient().os.readFileAsDataUrl.query(input);
}

export const filePersistHost = {
  saveClipboardImage: (input: {
    base64Data: string;
    mimeType: string;
    originalName: string;
  }) => hostClient().os.saveClipboardImage.mutate(input),
  saveClipboardText: (input: { text: string; originalName?: string }) =>
    hostClient().os.saveClipboardText.mutate(input),
  saveClipboardFile: (input: { base64Data: string; originalName: string }) =>
    hostClient().os.saveClipboardFile.mutate(input),
  downscaleImageFile: (input: { filePath: string }) =>
    hostClient().os.downscaleImageFile.mutate(input),
};
