import { CaretDownIcon, CaretRightIcon, PlusIcon } from "@phosphor-icons/react";
import {
  type HomeGroup,
  UNGROUPED_GROUP_KEY,
} from "@posthog/core/home/homeFilters";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { HomeWorkRow } from "@posthog/ui/features/home/components/HomeWorkRow";
import { ProjectMenu } from "@posthog/ui/features/home/components/ProjectMenu";
import { useHomeViewStore } from "@posthog/ui/features/home/homeViewStore";
import type { HomeRowActions } from "@posthog/ui/features/home/useHomeActions";
import { memo } from "react";

export interface HomeProjectOption {
  id: string;
  name: string;
}

/** No projects in this space, as one shared array so a memoized row holds. */
const NO_PROJECTS: HomeProjectOption[] = [];

function HomeGroupSectionInner({
  group,
  collapsed,
  actions,
  projectsBySpace,
  showProject,
  showSpace,
  groupsAreProjects,
  onAddToGroup,
}: {
  group: HomeGroup;
  collapsed: boolean;
  actions: HomeRowActions;
  projectsBySpace: Map<string, HomeProjectOption[]>;
  showProject: boolean;
  showSpace: boolean;
  /** Whether every heading names a project, which is what the header acts on. */
  groupsAreProjects: boolean;
  onAddToGroup: (group: HomeGroup) => void;
}) {
  const toggleGroup = useHomeViewStore((state) => state.toggleGroup);
  const Caret = collapsed ? CaretRightIcon : CaretDownIcon;
  // The unfiled pile is not a project, so there is nothing to add work to and
  // nothing to rename or delete.
  const isProject = groupsAreProjects && group.key !== UNGROUPED_GROUP_KEY;

  return (
    <section>
      <div className="sticky top-0 z-10 flex h-8 items-center gap-2 border-(--gray-4) border-b bg-(--gray-2) px-3">
        <button
          type="button"
          onClick={() => toggleGroup(group.key)}
          aria-expanded={!collapsed}
          className="flex min-w-0 items-center gap-1.5 font-medium text-(--gray-12) text-sm hover:text-(--foreground)"
        >
          <Caret size={12} className="shrink-0 text-(--gray-10)" aria-hidden />
          <span className="truncate">{group.label}</span>
          <span className="text-(--gray-10) tabular-nums">
            {group.rows.length}
          </span>
        </button>
        <div className="flex-1" />
        {isProject ? (
          <>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="default"
                    size="icon-sm"
                    aria-label={`Add a todo to ${group.label}`}
                    onClick={() => onAddToGroup(group)}
                  >
                    <PlusIcon size={14} />
                  </Button>
                }
              />
              <TooltipContent>Add a todo here</TooltipContent>
            </Tooltip>
            <ProjectMenu projectId={group.key} projectName={group.label} />
          </>
        ) : null}
      </div>
      {collapsed
        ? null
        : group.rows.map((row) => (
            <HomeWorkRow
              key={row.key}
              row={row}
              actions={actions}
              projectOptions={projectsBySpace.get(row.spaceId) ?? NO_PROJECTS}
              showProject={showProject}
              showSpace={showSpace}
            />
          ))}
    </section>
  );
}

const HomeGroupSection = memo(HomeGroupSectionInner);

/**
 * The table itself: sections in the order the grouping put them, each a sticky
 * heading over its rows. There is no header row. Every column but the title is
 * a glyph or a chip that says what it is, and a header band over a list this
 * dense costs more than it explains.
 */
export function HomeTable({
  groups,
  actions,
  projectsBySpace,
  showProject,
  showSpace,
  groupsAreProjects,
  onAddToGroup,
}: {
  groups: HomeGroup[];
  actions: HomeRowActions;
  projectsBySpace: Map<string, HomeProjectOption[]>;
  showProject: boolean;
  showSpace: boolean;
  groupsAreProjects: boolean;
  onAddToGroup: (group: HomeGroup) => void;
}) {
  const collapsedGroups = useHomeViewStore((state) => state.collapsedGroups);

  return (
    <div className="flex-1 overflow-y-auto">
      {groups.map((group) => (
        <HomeGroupSection
          key={group.key}
          group={group}
          collapsed={collapsedGroups[group.key] ?? false}
          actions={actions}
          projectsBySpace={projectsBySpace}
          showProject={showProject}
          showSpace={showSpace}
          groupsAreProjects={groupsAreProjects}
          onAddToGroup={onAddToGroup}
        />
      ))}
    </div>
  );
}
