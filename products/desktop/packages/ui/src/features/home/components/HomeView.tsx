import {
  KanbanIcon,
  NoteIcon,
  PlusIcon,
  StackIcon,
} from "@phosphor-icons/react";
import {
  countHomeFilters,
  filterHomeRows,
  groupHomeRows,
  type HomeGroup,
  homeFacets,
  sortHomeRows,
} from "@posthog/core/home/homeFilters";
import type { HomeRow } from "@posthog/core/home/homeRows";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Skeleton,
} from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  type HomeProjectOption,
  HomeTable,
} from "@posthog/ui/features/home/components/HomeTable";
import { HomeToolbar } from "@posthog/ui/features/home/components/HomeToolbar";
import { NewProjectDialog } from "@posthog/ui/features/home/components/NewProjectDialog";
import {
  NoteDialog,
  type NoteDialogTarget,
} from "@posthog/ui/features/home/components/NoteDialog";
import { useHomeProjectsStore } from "@posthog/ui/features/home/homeProjectsStore";
import { useHomeViewStore } from "@posthog/ui/features/home/homeViewStore";
import { useHomeActions } from "@posthog/ui/features/home/useHomeActions";
import {
  useHomeRows,
  usePinnedSpaces,
} from "@posthog/ui/features/home/useHomeWork";
import { navigateToCanvas } from "@posthog/ui/router/navigationBridge";
import { useCallback, useMemo, useState } from "react";

/**
 * The home page: every piece of work across the spaces this reader pinned, in
 * one table.
 *
 * Fetching only. Everything the page draws lives in {@link HomePage}, which
 * takes it all as props so the surface can be rendered without a backend.
 */
export function HomeView() {
  const { spaces, isLoading: spacesLoading } = usePinnedSpaces();
  const { rows, isLoading } = useHomeRows();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });

  const spaceOptions = useMemo(
    () => spaces.map((space) => ({ id: space.id, name: space.name })),
    [spaces],
  );

  return (
    <HomePage
      spaces={spaceOptions}
      rows={rows}
      isLoading={spacesLoading || isLoading}
      currentUser={currentUser ?? null}
    />
  );
}

export interface HomePageSpace {
  id: string;
  name: string;
}

/**
 * The table is the whole page. Its own chrome is one toolbar, because the point
 * of the surface is to answer "what is happening" in a glance rather than to be
 * navigated.
 */
export function HomePage({
  spaces,
  rows,
  isLoading,
  currentUser,
}: {
  spaces: HomePageSpace[];
  rows: HomeRow[];
  isLoading: boolean;
  currentUser: UserBasic | null;
}) {
  const projects = useHomeProjectsStore((state) => state.projects);

  const query = useHomeViewStore((state) => state.query);
  const filters = useHomeViewStore((state) => state.filters);
  const groupBy = useHomeViewStore((state) => state.groupBy);
  const sort = useHomeViewStore((state) => state.sort);
  const clearFilters = useHomeViewStore((state) => state.clearFilters);
  const setQuery = useHomeViewStore((state) => state.setQuery);

  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [noteTarget, setNoteTarget] = useState<NoteDialogTarget | null>(null);

  const openNote = useCallback(
    (row: HomeRow) => setNoteTarget({ mode: "edit", noteId: row.id }),
    [],
  );
  const actions = useHomeActions({ onOpenNote: openNote });

  const facets = useMemo(() => homeFacets(rows), [rows]);
  const visible = useMemo(
    () => sortHomeRows(filterHomeRows(rows, { query, filters }), sort),
    [rows, query, filters, sort],
  );
  const groups = useMemo(
    () => groupHomeRows(visible, groupBy),
    [visible, groupBy],
  );

  const spaceNameById = useMemo(
    () => new Map(spaces.map((space) => [space.id, space.name])),
    [spaces],
  );

  // One array per space, rebuilt only when the projects change, so a memoized
  // row keeps its props across the table's polling refreshes.
  const projectsBySpace = useMemo(() => {
    const bySpace = new Map<string, HomeProjectOption[]>();
    for (const project of Object.values(projects)) {
      const existing = bySpace.get(project.spaceId);
      const option = { id: project.id, name: project.name };
      if (existing) existing.push(option);
      else bySpace.set(project.spaceId, [option]);
    }
    return bySpace;
  }, [projects]);

  const projectOptions = useMemo(
    () =>
      Object.values(projects).map((project) => ({
        id: project.id,
        name: project.name,
        spaceName: spaceNameById.get(project.spaceId) ?? "",
      })),
    [projects, spaceNameById],
  );

  // Only reachable from a project heading: under any other grouping there is no
  // one project the new work would belong to.
  const addToGroup = useCallback(
    (group: HomeGroup) =>
      setNoteTarget({ mode: "create", kind: "todo", projectId: group.key }),
    [],
  );

  const activeFilterCount = countHomeFilters(filters);
  const hasProjects = projectOptions.length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center gap-2 px-4 pt-4 pb-2">
        <h1 className="font-semibold text-(--gray-12) text-lg">Home</h1>
        <span className="text-muted-foreground text-sm">
          {spaces.length === 1
            ? "1 pinned space"
            : `${spaces.length} pinned spaces`}
        </span>
        <div className="flex-1" />
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant="primary"
                size="sm"
                disabled={spaces.length === 0}
              >
                <PlusIcon size={14} />
                New
              </Button>
            }
          />
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => setProjectDialogOpen(true)}>
              Project…
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {/* A plan and a todo both live inside a project, so there is
                nothing to file them under until one exists. */}
            <DropdownMenuItem
              disabled={!hasProjects}
              onClick={() => setNoteTarget({ mode: "create", kind: "todo" })}
            >
              Todo…
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!hasProjects}
              onClick={() => setNoteTarget({ mode: "create", kind: "plan" })}
            >
              Plan…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      {spaces.length > 0 ? (
        <HomeToolbar facets={facets} activeFilterCount={activeFilterCount} />
      ) : null}

      {isLoading ? (
        <HomeTableSkeleton />
      ) : spaces.length === 0 ? (
        <NoPinnedSpaces />
      ) : visible.length === 0 ? (
        <NothingToShow
          narrowed={activeFilterCount > 0 || query.length > 0}
          onClear={() => {
            clearFilters();
            setQuery("");
          }}
        />
      ) : (
        <HomeTable
          groups={groups}
          actions={actions}
          projectsBySpace={projectsBySpace}
          showProject={groupBy !== "project"}
          showSpace={groupBy !== "space"}
          groupsAreProjects={groupBy === "project"}
          onAddToGroup={addToGroup}
        />
      )}

      <NewProjectDialog
        open={projectDialogOpen}
        onOpenChange={setProjectDialogOpen}
        spaces={spaces}
        currentUser={currentUser}
      />
      <NoteDialog
        target={noteTarget}
        onClose={() => setNoteTarget(null)}
        projects={projectOptions}
        currentUser={currentUser}
      />
    </div>
  );
}

/** One placeholder per row the table will draw, so the page doesn't jump. */
const SKELETON_ROWS = ["1", "2", "3", "4", "5", "6", "7", "8"];

function HomeTableSkeleton() {
  return (
    <output aria-label="Loading work" className="flex flex-col gap-px p-3">
      {SKELETON_ROWS.map((row) => (
        <Skeleton key={row} className="h-9 w-full" />
      ))}
    </output>
  );
}

function NoPinnedSpaces() {
  return (
    <Empty className="flex-1">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <StackIcon />
        </EmptyMedia>
        <EmptyTitle>No pinned spaces yet</EmptyTitle>
        <EmptyDescription>
          Home shows the work in the spaces you pin. Star a space to start
          following it here.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="primary" onClick={() => navigateToCanvas()}>
          Browse spaces
        </Button>
      </EmptyContent>
    </Empty>
  );
}

function NothingToShow({
  narrowed,
  onClear,
}: {
  narrowed: boolean;
  onClear: () => void;
}) {
  return (
    <Empty className="flex-1">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          {narrowed ? <NoteIcon /> : <KanbanIcon />}
        </EmptyMedia>
        <EmptyTitle>
          {narrowed ? "Nothing matches" : "Nothing here yet"}
        </EmptyTitle>
        <EmptyDescription>
          {narrowed
            ? "No work in your pinned spaces matches the search and filters."
            : "Work started in your pinned spaces shows up here."}
        </EmptyDescription>
      </EmptyHeader>
      {narrowed ? (
        <EmptyContent>
          <Button variant="outline" onClick={onClear}>
            Clear search and filters
          </Button>
        </EmptyContent>
      ) : null}
    </Empty>
  );
}
