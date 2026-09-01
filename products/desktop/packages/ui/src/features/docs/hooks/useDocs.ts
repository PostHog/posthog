import {
  createDoc,
  type DocSchemas,
  deleteDoc,
  listDocs,
  reorderDocs,
  retrieveDoc,
  updateDoc,
} from "@posthog/api-client/docs";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import {
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { docsKeys } from "./docsKeys";
import { useDocsClient } from "./useDocsClient";

/** A doc write shows up in two places: the tab row and the space's docs list. */
function invalidateDocLists(
  queryClient: QueryClient,
  projectId: string | null,
  channelId: string,
): void {
  void queryClient.invalidateQueries({
    queryKey: docsKeys.list(projectId, channelId),
  });
  void queryClient.invalidateQueries({
    queryKey: docsKeys.home(projectId, channelId),
  });
}

const DOC_LIST_POLL_INTERVAL_MS = 60_000;

/** Every doc in a space, in tab order. */
export function useDocs(channelId: string) {
  const docsClient = useDocsClient();
  return useQuery({
    queryKey: docsKeys.list(docsClient?.projectId ?? null, channelId),
    queryFn: async (): Promise<DocSchemas.DocSummary[]> => {
      if (!docsClient) throw new Error("Not authenticated");
      return listDocs(docsClient.client, docsClient.projectId, channelId);
    },
    enabled: !!docsClient && !!channelId,
    staleTime: 15_000,
    refetchInterval: DOC_LIST_POLL_INTERVAL_MS,
    meta: AUTH_SCOPED_QUERY_META,
  });
}

/**
 * One doc with its body. Refetched only on demand: while the doc is open the
 * live stream is what keeps it current.
 */
export function useDoc(docId: string | null) {
  const docsClient = useDocsClient();
  return useQuery({
    queryKey: docsKeys.detail(docsClient?.projectId ?? null, docId ?? ""),
    queryFn: async (): Promise<DocSchemas.Doc> => {
      if (!docsClient || !docId) throw new Error("No doc to load");
      return retrieveDoc(docsClient.client, docsClient.projectId, docId);
    },
    enabled: !!docsClient && !!docId,
    staleTime: Number.POSITIVE_INFINITY,
    meta: AUTH_SCOPED_QUERY_META,
  });
}

export function useCreateDoc(channelId: string) {
  const docsClient = useDocsClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      title?: string;
      template?: DocSchemas.DocTemplate;
    }): Promise<DocSchemas.Doc> => {
      if (!docsClient) throw new Error("Not authenticated");
      return createDoc(docsClient.client, docsClient.projectId, {
        channel: channelId,
        ...input,
      });
    },
    onSuccess: () => {
      invalidateDocLists(queryClient, docsClient?.projectId ?? null, channelId);
    },
  });
}

/**
 * Starts a doc and opens it.
 *
 * Creating without opening leaves the person looking at the list they just left,
 * so both the empty state and the tab row's plus use this.
 */
export function useCreateDocAndOpen(channelId: string) {
  const createDoc = useCreateDoc(channelId);
  const navigate = useNavigate();

  return {
    isPending: createDoc.isPending,
    start: (template: DocSchemas.DocTemplate) => {
      void createDoc.mutateAsync({ template }).then((doc) => {
        void navigate({
          to: "/spaces/$channelId/docs/$docId",
          params: { channelId, docId: doc.id },
        });
      });
    },
  };
}

export function useUpdateDoc(channelId: string) {
  const docsClient = useDocsClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      docId: string;
      changes: DocSchemas.DocUpdate;
    }): Promise<DocSchemas.Doc> => {
      if (!docsClient) throw new Error("Not authenticated");
      return updateDoc(
        docsClient.client,
        docsClient.projectId,
        input.docId,
        input.changes,
      );
    },
    onSuccess: (doc) => {
      queryClient.setQueryData(
        docsKeys.detail(docsClient?.projectId ?? null, doc.id),
        doc,
      );
      invalidateDocLists(queryClient, docsClient?.projectId ?? null, channelId);
    },
  });
}

export function useDeleteDoc(channelId: string) {
  const docsClient = useDocsClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (docId: string): Promise<void> => {
      if (!docsClient) throw new Error("Not authenticated");
      await deleteDoc(docsClient.client, docsClient.projectId, docId);
    },
    onSuccess: () => {
      invalidateDocLists(queryClient, docsClient?.projectId ?? null, channelId);
    },
  });
}

export function useReorderDocs(channelId: string) {
  const docsClient = useDocsClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (docIds: string[]): Promise<void> => {
      if (!docsClient) throw new Error("Not authenticated");
      await reorderDocs(
        docsClient.client,
        docsClient.projectId,
        channelId,
        docIds,
      );
    },
    onSuccess: () => {
      invalidateDocLists(queryClient, docsClient?.projectId ?? null, channelId);
    },
  });
}
