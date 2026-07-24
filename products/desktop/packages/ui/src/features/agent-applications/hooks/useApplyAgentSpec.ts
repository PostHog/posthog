import type {
  AgentRevision,
  AgentRevisionState,
  AgentSpec,
} from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/**
 * Apply a spec change ("create draft and apply changes"): if the target
 * revision is already a draft, PATCH its spec in place; otherwise clone it to a
 * fresh draft first and PATCH that. Freeze/promote stay separate (the revision
 * bar's lifecycle buttons) — this only lands the edit on an editable draft.
 *
 * Returns the revision the change landed on so the caller can select it (it's a
 * new draft whenever the source wasn't a draft).
 */
export function useApplyAgentSpec(
  idOrSlug: string,
  applicationId: string | undefined,
) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);

  return useMutation<
    AgentRevision,
    Error,
    { revision: { id: string; state: AgentRevisionState }; spec: AgentSpec }
  >({
    mutationFn: async ({ revision, spec }) => {
      let targetId = revision.id;
      const clonedDraft = revision.state !== "draft";
      if (clonedDraft) {
        if (!applicationId) {
          throw new Error("Application not loaded yet");
        }
        const draft = await client.createAgentDraftRevisionFrom(
          applicationId,
          revision.id,
        );
        targetId = draft.id;
      }
      try {
        return await client.updateAgentRevisionSpec(idOrSlug, targetId, spec);
      } catch (err) {
        // If we cloned a fresh draft and the spec PATCH then failed, that
        // draft is an orphan (a copy of the source with no edit landed).
        // Archive it best-effort so repeated failed applies don't pile up
        // empty drafts; never mask the original error. A pre-existing draft
        // passed in by the caller is left untouched.
        if (clonedDraft) {
          await client
            .transitionAgentRevision(idOrSlug, targetId, "archive")
            .catch(() => undefined);
        }
        throw err;
      }
    },
    onSuccess: () => {
      for (const key of [
        agentApplicationsKeys.detail(projectId, idOrSlug),
        agentApplicationsKeys.revisions(projectId, idOrSlug),
        agentApplicationsKeys.revisionPrefix(projectId, idOrSlug),
      ]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
}
