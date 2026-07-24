import { formatRelativeTimeShort } from "@posthog/shared";
import type { AgentMemoryTreeNode } from "@posthog/shared/agent-platform-types";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Flex, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import {
  useAgentMemoryFile,
  useAgentMemorySearch,
  useAgentMemoryTable,
  useAgentMemoryTables,
  useAgentMemoryTree,
} from "../hooks/useAgentMemory";
import { AgentDetailLayout } from "./AgentDetailLayout";
import { FileExplorer, type FileTreeNode } from "./FileExplorer";

type View = "files" | "tables";

/**
 * Per-agent Memory pane: the agent's S3-backed memory store, browsed through the
 * same reusable {@link FileExplorer} as the config bundle — a folder tree + read
 * view with BM25 search, plus the JSONL reference tables. Render-only;
 * create/update/delete is deferred (and operational, not authoring, if added).
 */
export function AgentMemoryPane({ idOrSlug }: { idOrSlug: string }) {
  const [view, setView] = useState<View>("files");

  return (
    <AgentDetailLayout idOrSlug={idOrSlug} activeTab="memory" fill>
      <Flex direction="column" className="h-full min-h-0">
        <Flex gap="2" className="shrink-0 border-(--gray-5) border-b px-4 py-2">
          {(["files", "tables"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              className={`rounded-(--radius-2) px-3 py-1 text-[12px] capitalize ${
                v === view
                  ? "bg-(--accent-3) font-medium text-gray-12"
                  : "text-gray-11 hover:bg-(--gray-3)"
              }`}
            >
              {v}
            </button>
          ))}
        </Flex>
        <div className="min-h-0 flex-1">
          {view === "files" ? (
            <MemoryFiles idOrSlug={idOrSlug} />
          ) : (
            <MemoryTables idOrSlug={idOrSlug} />
          )}
        </div>
      </Flex>
    </AgentDetailLayout>
  );
}

function toFileTree(node: AgentMemoryTreeNode): FileTreeNode {
  return {
    type: node.type,
    name: node.name,
    path: node.path,
    description: node.description,
    children: node.children?.map(toFileTree),
  };
}

function MemoryFiles({ idOrSlug }: { idOrSlug: string }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const { data: root, isLoading, isError } = useAgentMemoryTree(idOrSlug);
  const search = useAgentMemorySearch(idOrSlug, query);

  const tree = useMemo(() => (root ? toFileTree(root) : null), [root]);
  const results = useMemo(
    () =>
      (search.data ?? []).map((r) => ({
        path: r.path,
        description: r.description,
        snippet: r.snippet ?? undefined,
        score: r.score,
      })),
    [search.data],
  );

  return (
    <FileExplorer
      tree={tree}
      selectedPath={selected}
      onSelectPath={setSelected}
      loading={isLoading}
      error={isError ? new Error("Couldn't load memory") : null}
      emptyMessage="No memory files yet."
      storageKey="agent-memory-explorer"
      search={{
        query,
        onChange: setQuery,
        results: query.trim() ? results : null,
        loading: search.isLoading,
        placeholder: "Search memory…",
      }}
    >
      {selected ? (
        <MemoryFileDetail idOrSlug={idOrSlug} path={selected} />
      ) : (
        <Centered>Select a memory file to read it.</Centered>
      )}
    </FileExplorer>
  );
}

function MemoryFileDetail({
  idOrSlug,
  path,
}: {
  idOrSlug: string;
  path: string;
}) {
  const { data: file, isLoading, isError } = useAgentMemoryFile(idOrSlug, path);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-(--gray-5) border-b px-5 py-3">
        <Text className="block truncate font-medium text-[13px] text-gray-12 [font-family:var(--font-mono)]">
          {path}
        </Text>
        {file ? (
          <Flex align="center" gap="2" wrap="wrap" className="mt-1">
            {file.tags.map((t) => (
              <Badge key={t} color="gray">
                {t}
              </Badge>
            ))}
            {file.updated_at ? (
              <Text className="text-[11px] text-gray-10">
                updated {formatRelativeTimeShort(file.updated_at)}
              </Text>
            ) : null}
          </Flex>
        ) : null}
        {file?.description ? (
          <Text className="mt-1 block text-[12px] text-gray-11 leading-snug">
            {file.description}
          </Text>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {isLoading ? (
          <div className="h-40 animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)" />
        ) : isError || !file ? (
          <Text className="text-[12px] text-gray-10">
            Couldn't load this file.
          </Text>
        ) : (
          <div className="text-[13px]">
            <MarkdownRenderer content={file.content} />
          </div>
        )}
      </div>
    </div>
  );
}

function MemoryTables({ idOrSlug }: { idOrSlug: string }) {
  const [selected, setSelected] = useState<string | null>(null);
  const { data: tables, isLoading, isError } = useAgentMemoryTables(idOrSlug);

  const tree = useMemo<FileTreeNode | null>(
    () =>
      tables
        ? {
            type: "folder",
            name: "root",
            children: tables.map((t) => ({
              type: "file" as const,
              name: t.name,
              path: t.name,
              description: `${t.size} row${t.size === 1 ? "" : "s"}`,
            })),
          }
        : null,
    [tables],
  );

  return (
    <FileExplorer
      tree={tree}
      selectedPath={selected}
      onSelectPath={setSelected}
      loading={isLoading}
      error={isError ? new Error("Couldn't load tables") : null}
      emptyMessage="No tables yet."
      storageKey="agent-memory-tables"
    >
      {selected ? (
        <MemoryTableDetail idOrSlug={idOrSlug} name={selected} />
      ) : (
        <Centered>Select a table to read its rows.</Centered>
      )}
    </FileExplorer>
  );
}

function MemoryTableDetail({
  idOrSlug,
  name,
}: {
  idOrSlug: string;
  name: string;
}) {
  const { data, isLoading, isError } = useAgentMemoryTable(idOrSlug, name);
  const columns = useMemo(() => {
    const cols = new Set<string>();
    for (const row of data?.rows ?? []) {
      for (const k of Object.keys(row)) cols.add(k);
    }
    return [...cols];
  }, [data]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-(--gray-5) border-b px-5 py-3">
        <Text className="block font-medium text-[13px] text-gray-12 [font-family:var(--font-mono)]">
          {name}
        </Text>
        {data ? (
          <Text className="text-[11px] text-gray-10">
            showing {data.returned} of {data.total} rows
          </Text>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
        {isLoading ? (
          <div className="h-40 animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)" />
        ) : isError || !data ? (
          <Text className="text-[12px] text-gray-10">
            Couldn't load this table.
          </Text>
        ) : data.rows.length === 0 ? (
          <Text className="text-[12px] text-gray-10">No rows.</Text>
        ) : (
          <div className="overflow-x-auto rounded-(--radius-2) border border-border">
            <table className="w-full border-collapse text-[12px]">
              <thead>
                <tr className="border-(--gray-5) border-b bg-(--gray-2)">
                  {columns.map((c) => (
                    <th
                      key={c}
                      className="whitespace-nowrap px-3 py-2 text-left font-medium text-gray-11 [font-family:var(--font-mono)]"
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr
                    // biome-ignore lint/suspicious/noArrayIndexKey: table rows have no stable id
                    key={i}
                    className="border-(--gray-4) border-b last:border-0"
                  >
                    {columns.map((c) => (
                      <td
                        key={c}
                        className="max-w-xs truncate px-3 py-1.5 text-gray-12"
                        title={cellText(row[c])}
                      >
                        {cellText(row[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function cellText(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center px-6 text-center text-[12px] text-gray-10">
      {children}
    </div>
  );
}
