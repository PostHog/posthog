import {
  ChatCircleIcon,
  DotsThreeIcon,
  type Icon,
  ListChecksIcon,
  NoteIcon,
  PushPinIcon,
  ShapesIcon,
} from "@phosphor-icons/react";
import type { HomeRow } from "@posthog/core/home/homeRows";
import {
  HOME_STATUS_LABELS,
  HOME_STATUS_ORDER,
  HOME_WORK_KIND_LABELS,
} from "@posthog/core/home/schemas";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import {
  HomeStatusCell,
  HomeStatusIcon,
} from "@posthog/ui/features/home/components/HomeStatusIcon";
import type { HomeRowActions } from "@posthog/ui/features/home/useHomeActions";
import { memo } from "react";

/**
 * The glyph that says what kind of work a row is. Sessions borrow the chat
 * glyph they wear elsewhere in the app, canvases the shapes glyph the space's
 * own list gives an unclassified canvas.
 */
const KIND_ICON: Record<HomeRow["kind"], Icon> = {
  session: ChatCircleIcon,
  canvas: ShapesIcon,
  plan: NoteIcon,
  todo: ListChecksIcon,
};

/** Dim, fixed-width trailing metadata, so the columns line up down the table. */
const META_CLASS = "shrink-0 text-[11px] text-muted-foreground";

function HomeWorkRowInner({
  row,
  actions,
  projectOptions,
  showProject,
  showSpace,
}: {
  row: HomeRow;
  actions: HomeRowActions;
  /** Projects in this row's own space: work can only move within a space. */
  projectOptions: { id: string; name: string }[];
  /** False when the group heading above already names it. */
  showProject: boolean;
  showSpace: boolean;
}) {
  const KindIcon = KIND_ICON[row.kind];
  // Plans and todos are the only work this app owns outright, so they are the
  // only rows whose status and existence the menu can actually change.
  const isNote = row.kind === "plan" || row.kind === "todo";

  return (
    <div className="group flex h-9 items-center gap-2 border-(--gray-4) border-b px-3 text-sm last:border-b-0 focus-within:bg-(--gray-2) hover:bg-(--gray-2)">
      {/* A real button rather than a clickable row div: it is one tab stop that
          Enter and Space already work on, and it lets the actions menu sit
          beside it instead of nested inside another button. */}
      <button
        type="button"
        onClick={() => actions.open(row)}
        className="flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-none"
      >
        <HomeStatusCell status={row.status} />

        <span className={`${META_CLASS} w-12 tabular-nums`}>
          {row.reference ?? ""}
        </span>

        <Tooltip>
          <TooltipTrigger
            render={
              <span className="flex size-4 shrink-0 items-center justify-center">
                <KindIcon size={14} className="text-(--gray-10)" aria-hidden />
              </span>
            }
          />
          <TooltipContent>{HOME_WORK_KIND_LABELS[row.kind]}</TooltipContent>
        </Tooltip>

        <span className="min-w-0 flex-1 truncate">{row.title}</span>

        {row.pinned ? (
          <PushPinIcon
            size={12}
            weight="fill"
            className="shrink-0 text-(--gray-10)"
            aria-label="Pinned"
          />
        ) : null}

        {showProject && row.projectName ? (
          <span className="hidden max-w-40 shrink-0 truncate rounded-(--radius-2) bg-(--gray-3) px-1.5 py-0.5 text-(--gray-11) text-[11px] sm:block">
            {row.projectName}
          </span>
        ) : null}

        {showSpace ? (
          <span
            className={`${META_CLASS} hidden w-32 truncate text-right md:block`}
          >
            #{row.spaceName}
          </span>
        ) : null}

        <span className="flex w-6 shrink-0 justify-center">
          {row.assignee ? <UserAvatar user={row.assignee} size="xs" /> : null}
        </span>

        <span className={`${META_CLASS} w-10 text-right`}>
          {formatRelativeTimeShort(row.updatedAt)}
        </span>
      </button>

      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="default"
              size="icon-sm"
              aria-label={`Actions for ${row.title}`}
              className="shrink-0 opacity-0 group-hover:opacity-100 data-[popup-open]:opacity-100"
            >
              <DotsThreeIcon size={16} />
            </Button>
          }
        />
        <DropdownMenuContent align="end">
          {isNote ? (
            <>
              <DropdownMenuGroup>
                <DropdownMenuLabel>Status</DropdownMenuLabel>
                {HOME_STATUS_ORDER.map((status) => (
                  <DropdownMenuItem
                    key={status}
                    onClick={() => actions.setNoteStatus(row, status)}
                  >
                    <HomeStatusIcon status={status} size={14} />
                    {HOME_STATUS_LABELS[status]}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => actions.remove(row)}>
                Delete
              </DropdownMenuItem>
            </>
          ) : (
            <>
              <DropdownMenuGroup>
                <DropdownMenuLabel>Move to project</DropdownMenuLabel>
                {projectOptions.length === 0 ? (
                  <DropdownMenuItem disabled>
                    No projects in #{row.spaceName} yet
                  </DropdownMenuItem>
                ) : (
                  projectOptions.map((project) => (
                    <DropdownMenuItem
                      key={project.id}
                      onClick={() => actions.fileToProject(row, project.id)}
                    >
                      {project.name}
                    </DropdownMenuItem>
                  ))
                )}
              </DropdownMenuGroup>
              {row.projectId ? (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => actions.fileToProject(row, null)}
                  >
                    Remove from project
                  </DropdownMenuItem>
                </>
              ) : null}
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

/**
 * Memoized because the table polls: every refresh hands the list new row
 * objects, and a screenful of rows each carrying a dropdown, two tooltips and
 * an avatar is enough re-render to show up as scroll jank.
 */
export const HomeWorkRow = memo(HomeWorkRowInner);
