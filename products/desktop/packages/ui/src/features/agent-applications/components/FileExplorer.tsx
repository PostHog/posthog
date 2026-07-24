import {
  CaretDownIcon,
  CaretRightIcon,
  FileIcon,
  FolderIcon,
  FolderOpenIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react";
import { type ReactNode, useMemo, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

export interface FileTreeNode {
  type: "file" | "folder";
  name: string;
  /** Set on files (and optionally folders) — the click target for selection. */
  path?: string;
  /** One-line annotation under the name (e.g. a skill/memory description). */
  description?: string;
  /** Icon override for the row. Defaults to a generic file/folder icon. */
  icon?: ReactNode;
  /** Right-aligned slot (e.g. an approval lock or a "needs attention" badge). */
  trailing?: ReactNode;
  children?: FileTreeNode[];
}

export interface FileExplorerSearchResult {
  path: string;
  name?: string;
  description?: string;
  snippet?: string;
  score?: number;
}

interface SearchConfig {
  query: string;
  onChange: (query: string) => void;
  /** Non-null = results mode (flat list). Null/undefined = tree mode. */
  results?: FileExplorerSearchResult[] | null;
  placeholder?: string;
  loading?: boolean;
}

export interface FileExplorerProps {
  tree: FileTreeNode | null;
  selectedPath: string | null;
  onSelectPath: (path: string) => void;
  /** Optional search input + flat results override (e.g. memory BM25 search). */
  search?: SearchConfig;
  /** Top-of-left-pane action (e.g. a "+ New" button). */
  topAction?: ReactNode;
  /** Right-pane content — the consumer renders whatever fits the selection. */
  children: ReactNode;
  emptyMessage?: string;
  loading?: boolean;
  error?: Error | null;
  /**
   * Distinct localStorage key per surface so the bundle tree and the memory
   * tree persist their widths independently.
   */
  storageKey: string;
}

/**
 * Generic two-pane file explorer: a collapsible folder tree (or flat search
 * results) on the left, arbitrary `children` on the right. Selection is
 * controlled so URL state + refetch stay with the consumer. The same wrapper
 * backs the read-only config bundle and the editable memory surface, so the
 * two feel identical to navigate. Ported from the agent-console's FileExplorer.
 */
export function FileExplorer({
  tree,
  selectedPath,
  onSelectPath,
  search,
  topAction,
  children,
  emptyMessage = "No files yet.",
  loading,
  error,
  storageKey,
}: FileExplorerProps) {
  const searching = !!search && search.query.trim().length > 0;

  return (
    <PanelGroup
      direction="horizontal"
      autoSaveId={storageKey}
      className="h-full overflow-hidden bg-(--color-panel-solid)"
    >
      <Panel defaultSize={24} minSize={15} maxSize={42} order={1}>
        <div className="flex h-full flex-col bg-(--gray-2)">
          {search || topAction ? (
            <div className="space-y-2 border-(--gray-5) border-b px-2 py-2">
              {search ? (
                <div className="relative">
                  <MagnifyingGlassIcon
                    size={12}
                    className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2 text-gray-10"
                  />
                  <input
                    type="search"
                    value={search.query}
                    onChange={(e) => search.onChange(e.currentTarget.value)}
                    placeholder={search.placeholder ?? "Search…"}
                    className="h-7 w-full rounded-(--radius-1) border border-border bg-(--color-panel-solid) pr-2 pl-7 text-[12px]"
                  />
                </div>
              ) : null}
              {topAction ? <div>{topAction}</div> : null}
            </div>
          ) : null}
          <div className="min-h-0 flex-1 overflow-y-auto py-1.5">
            {loading ? (
              <div className="px-3 py-2 text-[12px] text-gray-10">Loading…</div>
            ) : error ? (
              <div className="px-3 py-2 text-(--red-11) text-[12px]">
                {error.message}
              </div>
            ) : searching ? (
              <SearchResultsList
                results={search?.results ?? []}
                loading={search?.loading}
                selectedPath={selectedPath}
                onSelectPath={onSelectPath}
              />
            ) : tree?.children && tree.children.length > 0 ? (
              <TreeView
                node={tree}
                selected={selectedPath}
                onSelect={onSelectPath}
                depth={0}
              />
            ) : (
              <div className="px-3 py-2 text-[12px] text-gray-10">
                {emptyMessage}
              </div>
            )}
          </div>
        </div>
      </Panel>
      <PanelResizeHandle className="w-px bg-(--gray-5) transition-colors hover:bg-(--gray-7) data-[resize-handle-state=drag]:bg-(--accent-9)" />
      <Panel order={2}>
        <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
          {children}
        </div>
      </Panel>
    </PanelGroup>
  );
}

const ROW_SELECTED =
  "bg-(--accent-3) font-medium text-gray-12 shadow-[inset_2px_0_0_0_var(--accent-9)]";
const ROW_IDLE = "text-gray-11 hover:bg-(--gray-3) hover:text-gray-12";

function subtreeContains(node: FileTreeNode, path: string | null): boolean {
  if (!path) return false;
  for (const child of node.children ?? []) {
    if (child.path === path || subtreeContains(child, path)) return true;
  }
  return false;
}

function TreeView({
  node,
  selected,
  onSelect,
  depth,
}: {
  node: FileTreeNode;
  selected: string | null;
  onSelect: (path: string) => void;
  depth: number;
}) {
  return (
    <ul className="text-[12px]">
      {(node.children ?? []).map((child) =>
        child.type === "folder" ? (
          <FolderRow
            key={`d:${child.name}:${child.path ?? ""}`}
            node={child}
            selected={selected}
            onSelect={onSelect}
            depth={depth}
          />
        ) : (
          <FileRow
            key={`f:${child.path}`}
            node={child}
            selected={!!child.path && selected === child.path}
            onSelect={onSelect}
            depth={depth}
          />
        ),
      )}
    </ul>
  );
}

function FolderRow({
  node,
  selected,
  onSelect,
  depth,
}: {
  node: FileTreeNode;
  selected: string | null;
  onSelect: (path: string) => void;
  depth: number;
}) {
  const [open, setOpen] = useState(true);
  const isSelected = !!node.path && selected === node.path;
  const hasSelectedChild = useMemo(
    () => subtreeContains(node, selected),
    [node, selected],
  );
  // Auto-expand when the selection moves into a descendant. Reconciled during
  // render (not in an effect) so the folder opens before paint.
  const [prevHasSelectedChild, setPrevHasSelectedChild] =
    useState(hasSelectedChild);
  if (hasSelectedChild !== prevHasSelectedChild) {
    setPrevHasSelectedChild(hasSelectedChild);
    if (hasSelectedChild) setOpen(true);
  }

  return (
    <li>
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          if (node.path) onSelect(node.path);
        }}
        aria-current={isSelected ? "true" : undefined}
        className={`flex w-full cursor-pointer items-center gap-1 px-2 py-1 text-left transition-colors ${isSelected ? ROW_SELECTED : ROW_IDLE}`}
        style={{ paddingLeft: `${8 + depth * 12}px` }}
      >
        {open ? (
          <CaretDownIcon size={11} className="shrink-0" />
        ) : (
          <CaretRightIcon size={11} className="shrink-0" />
        )}
        {node.icon ??
          (open ? (
            <FolderOpenIcon size={14} className="shrink-0" />
          ) : (
            <FolderIcon size={14} className="shrink-0" />
          ))}
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
        {node.trailing ? (
          <span className="ml-auto shrink-0 pl-1">{node.trailing}</span>
        ) : null}
      </button>
      {open && node.children && node.children.length > 0 ? (
        <TreeView
          node={{ type: "folder", name: node.name, children: node.children }}
          selected={selected}
          onSelect={onSelect}
          depth={depth + 1}
        />
      ) : null}
    </li>
  );
}

function FileRow({
  node,
  selected,
  onSelect,
  depth,
}: {
  node: FileTreeNode;
  selected: boolean;
  onSelect: (path: string) => void;
  depth: number;
}) {
  if (!node.path) return null;
  const path = node.path;
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(path)}
        aria-current={selected ? "true" : undefined}
        className={`flex w-full cursor-pointer items-start gap-1.5 px-2 py-1 text-left transition-colors ${selected ? ROW_SELECTED : ROW_IDLE}`}
        style={{ paddingLeft: `${8 + depth * 12 + 16}px` }}
      >
        <span className="mt-px shrink-0">
          {node.icon ?? <FileIcon size={14} className="shrink-0" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate">{node.name}</span>
          {node.description ? (
            <span className="block truncate text-[10.5px] text-gray-9">
              {node.description}
            </span>
          ) : null}
        </span>
        {node.trailing ? (
          <span className="mt-px shrink-0 pl-1">{node.trailing}</span>
        ) : null}
      </button>
    </li>
  );
}

function SearchResultsList({
  results,
  loading,
  selectedPath,
  onSelectPath,
}: {
  results: FileExplorerSearchResult[];
  loading?: boolean;
  selectedPath: string | null;
  onSelectPath: (path: string) => void;
}) {
  if (loading) {
    return <div className="px-3 py-2 text-[12px] text-gray-10">Searching…</div>;
  }
  if (results.length === 0) {
    return (
      <div className="px-3 py-2 text-[12px] text-gray-10">No matches.</div>
    );
  }
  return (
    <ul className="space-y-0.5 px-1">
      {results.map((r) => {
        const isActive = selectedPath === r.path;
        return (
          <li key={r.path}>
            <button
              type="button"
              onClick={() => onSelectPath(r.path)}
              aria-current={isActive ? "true" : undefined}
              className={`flex w-full cursor-pointer flex-col gap-0.5 rounded-(--radius-1) px-2 py-1 text-left text-[12px] transition-colors ${isActive ? ROW_SELECTED : ROW_IDLE}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">{r.name ?? r.path}</span>
                {typeof r.score === "number" ? (
                  <span className="shrink-0 text-[10px] text-gray-9">
                    {r.score.toFixed(2)}
                  </span>
                ) : null}
              </div>
              {r.description ? (
                <span className="truncate text-[10.5px] text-gray-10">
                  {r.description}
                </span>
              ) : null}
              {r.snippet ? (
                <span className="truncate text-[10.5px] text-gray-9 italic">
                  {r.snippet}
                </span>
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
