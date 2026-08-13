import {
  type LoopSchemas,
  replaceLoopSkillBundles,
} from "@posthog/api-client/loops";
import { useHostTRPCClient } from "@posthog/host-router/react";
import {
  type QueryClient,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { isTrustedSkillDependency } from "../loopSkill";
import { loopsKeys } from "./loopsKeys";
import { useLoopsClient } from "./useLoopsClient";

function applyLoopToCache(
  queryClient: QueryClient,
  projectId: string | null,
  loop: LoopSchemas.Loop,
): void {
  queryClient.setQueryData(loopsKeys.detail(projectId, loop.id), loop);
  void queryClient.invalidateQueries({ queryKey: loopsKeys.list(projectId) });
}

export interface LoopLocalSkillRef {
  name: string;
  source: LoopSchemas.LoopSkillSourceEnum;
  path: string;
}

type HostClient = ReturnType<typeof useHostTRPCClient>;

async function buildSkillUploads(
  hostClient: HostClient,
  skill: LoopLocalSkillRef,
): Promise<LoopSchemas.LoopSkillBundleUpload[]> {
  const refs = await hostClient.skills.resolveDependencies.query([skill]);
  const dependencies = refs.filter((ref) => ref.name !== skill.name);
  const untrusted = dependencies.find(
    (dep) => !isTrustedSkillDependency(dep, skill),
  );
  if (untrusted) {
    throw new Error(
      `The ${skill.name} skill references /${untrusted.name}, which resolved to a skill ` +
        `outside its own scope (${untrusted.source}: ${untrusted.path}). Install ` +
        `${untrusted.name} alongside ${skill.name} and retry.`,
    );
  }
  const ordered = [skill, ...dependencies];
  const bundles = await Promise.all(
    ordered.map((ref) => hostClient.skills.bundleLocal.query(ref)),
  );
  return bundles.map((bundle) => ({
    file_name: bundle.fileName,
    skill_name: bundle.name,
    skill_source: bundle.source,
    content_sha256: bundle.contentSha256,
    bundle_format: "zip" as const,
    content_base64: bundle.contentBase64,
  }));
}

/**
 * Bundles a local skill plus its skill dependencies via workspace-server into
 * upload payloads. Host-only: nothing is persisted anywhere, so callers can run
 * it before writing the loop and fail fast with no partial state.
 */
export function useBundleLocalSkill() {
  const hostClient = useHostTRPCClient();
  return useMutation<
    LoopSchemas.LoopSkillBundleUpload[],
    Error,
    LoopLocalSkillRef
  >({
    mutationFn: (skill) => buildSkillUploads(hostClient, skill),
  });
}

/** Replaces a loop's stored bundles wholesale; an empty list detaches them all. */
export function useReplaceLoopSkillBundles() {
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<
    LoopSchemas.Loop,
    Error,
    { loopId: string; uploads: LoopSchemas.LoopSkillBundleUpload[] }
  >({
    mutationFn: async ({ loopId, uploads }) => {
      if (!loopsClient) throw new Error("Not authenticated");
      return await replaceLoopSkillBundles(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
        uploads,
      );
    },
    onSuccess: (loop) =>
      applyLoopToCache(queryClient, loopsClient?.projectId ?? null, loop),
  });
}

/**
 * Bundle-and-replace in one step, for refreshing an existing loop's snapshot
 * from the detail page. Detaching (null skill) never touches the host, so it
 * also works on hosts without a local filesystem.
 */
export function useSyncLoopSkillBundles() {
  const loopsClient = useLoopsClient();
  const hostClient = useHostTRPCClient();
  const queryClient = useQueryClient();

  return useMutation<
    LoopSchemas.Loop,
    Error,
    { loopId: string; skill: LoopLocalSkillRef | null }
  >({
    mutationFn: async ({ loopId, skill }) => {
      if (!loopsClient) throw new Error("Not authenticated");
      const uploads = skill ? await buildSkillUploads(hostClient, skill) : [];
      return await replaceLoopSkillBundles(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
        uploads,
      );
    },
    onSuccess: (loop) =>
      applyLoopToCache(queryClient, loopsClient?.projectId ?? null, loop),
  });
}
