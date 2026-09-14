import { ArrowLeft, ArrowRight, CaretDown } from "@phosphor-icons/react";
import {
  Button,
  Combobox,
  ComboboxCollection,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxGroup,
  ComboboxInput,
  ComboboxItem,
  ComboboxLabel,
  ComboboxList,
  ComboboxTrigger,
  Heading,
  Skeleton,
  Text,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { OAuthControls } from "@posthog/ui/features/auth/OAuthControls";
import {
  useAuthStateFetched,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useSelectProjectMutation } from "@posthog/ui/features/auth/useAuthMutations";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  type ProjectInfo,
  useProjects,
} from "@posthog/ui/features/projects/useProjects";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { FIELD_CONTENT_CLASS } from "@posthog/ui/styles/fieldTrigger";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useMemo, useRef, useState } from "react";
import { StepActions } from "./StepActions";

const log = logger.scope("project-select-step");

/** Base UI reads nested options from `items`, so groups carry that field. */
interface ProjectGroup {
  orgId: string;
  orgName: string;
  items: ProjectInfo[];
}

interface ProjectSelectStepProps {
  onNext: () => void;
  onBack?: () => void;
}

export function ProjectSelectStep({ onNext, onBack }: ProjectSelectStepProps) {
  const shouldReduceMotion = useReducedMotion() === true;
  const authFetched = useAuthStateFetched();
  const isAuthenticated =
    useAuthStateValue((state) => state.status) === "authenticated";
  const selectProjectMutation = useSelectProjectMutation();
  const currentProjectId = useAuthStateValue((state) => state.currentProjectId);
  const { projects, currentProject, groupedProjects } = useProjects();
  const [projectOpen, setProjectOpen] = useState(false);
  const projectAnchorRef = useRef<HTMLButtonElement>(null);

  const client = useOptionalAuthenticatedClient();
  const { data: fullUser, isLoading } = useCurrentUser({ client });

  const hasMultipleOrgs = (fullUser?.organizations?.length ?? 0) > 1;

  const sortedProjects = useMemo(
    () => projects.toSorted((a, b) => a.name.localeCompare(b.name)),
    [projects],
  );
  // Selecting a project already switches the org for it (AuthService.selectProject),
  // so the list stays grouped rather than gated behind a separate org picker.
  const sortedGroups = useMemo(
    () =>
      groupedProjects
        .toSorted((a, b) => a.orgName.localeCompare(b.orgName))
        .map((group) => ({
          orgId: group.orgId,
          orgName: group.orgName,
          items: group.projects.toSorted((a, b) =>
            a.name.localeCompare(b.name),
          ),
        })),
    [groupedProjects],
  );
  const selectedProject = useMemo(
    () => sortedProjects.find((p) => p.id === currentProjectId) ?? null,
    [sortedProjects, currentProjectId],
  );
  const projectLoading = isLoading || selectProjectMutation.isPending;

  return (
    <main className="w-full">
      <div className="mx-auto flex w-full max-w-[480px] flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          {/* biome-ignore lint/a11y/useHeadingContent: Quill supplies the heading text through this render target. */}
          <Heading size="xl" render={<h1 className="font-bold" />}>
            Choose a project
          </Heading>
          <Text size="sm" variant="muted">
            Choose the PostHog project you want to use with Desktop.
          </Text>
        </div>

        <div className="flex w-full flex-col gap-4">
          <AnimatePresence mode="wait">
            {!isAuthenticated && authFetched ? (
              <motion.div
                key="oauth"
                initial={{ opacity: 1 }}
                exit={shouldReduceMotion ? undefined : { opacity: 0, y: -4 }}
                transition={{ duration: 0.2 }}
                className="w-full"
              >
                <OAuthControls
                  onAuthInitiated={(region) =>
                    track(ANALYTICS_EVENTS.ONBOARDING_SIGN_IN_INITIATED, {
                      region,
                    })
                  }
                />
              </motion.div>
            ) : null}
          </AnimatePresence>

          {isAuthenticated && (
            <motion.div
              initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
              className="w-full"
            >
              <div className="flex w-full flex-col gap-2">
                <Text size="xs" variant="muted" weight="medium">
                  Project
                </Text>
                <Combobox
                  items={sortedGroups}
                  value={selectedProject}
                  onValueChange={(value) => {
                    const project = value as ProjectInfo | null;
                    if (project) {
                      selectProjectMutation.mutate(project.id, {
                        onError: (error) =>
                          log.error("Failed to select project", error),
                      });
                    }
                    setProjectOpen(false);
                  }}
                  open={projectOpen}
                  onOpenChange={setProjectOpen}
                  disabled={projectLoading}
                  itemToStringLabel={(project) => project.name}
                  itemToStringValue={(project) => String(project.id)}
                >
                  <ComboboxTrigger
                    render={
                      <Button
                        ref={projectAnchorRef}
                        type="button"
                        variant="outline"
                        size="lg"
                        left
                        aria-label={
                          projectLoading
                            ? "Loading project"
                            : `Project: ${currentProject?.name ?? "Select a project"}`
                        }
                        aria-busy={projectLoading || undefined}
                        className="h-auto min-h-14 w-full justify-between px-3 py-2"
                      >
                        {projectLoading ? (
                          <span
                            aria-hidden="true"
                            className="flex min-w-0 flex-1 flex-col gap-1.5"
                          >
                            <Skeleton className="h-3.5 w-28" />
                            <Skeleton className="h-2.5 w-20" />
                          </span>
                        ) : (
                          <span className="flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left">
                            <Text
                              render={<span />}
                              size="sm"
                              weight="medium"
                              className="min-w-0 max-w-full truncate"
                            >
                              {currentProject?.name ?? "Select a project..."}
                            </Text>
                            {currentProject && (
                              <Text
                                render={<span />}
                                size="xs"
                                variant="muted"
                                className="min-w-0 max-w-full truncate"
                              >
                                {currentProject.organization.name}
                              </Text>
                            )}
                          </span>
                        )}
                        <CaretDown
                          size={14}
                          className="shrink-0 text-muted-foreground"
                        />
                      </Button>
                    }
                  />
                  <ComboboxContent
                    anchor={projectAnchorRef}
                    side="bottom"
                    align="start"
                    sideOffset={4}
                    className={FIELD_CONTENT_CLASS}
                  >
                    <ComboboxInput
                      placeholder="Search projects..."
                      showTrigger={false}
                    />
                    <ComboboxEmpty>No projects found.</ComboboxEmpty>
                    <ComboboxList className="max-h-[240px]">
                      {(group: ProjectGroup) => (
                        <ComboboxGroup key={group.orgId} items={group.items}>
                          <ComboboxLabel>{group.orgName}</ComboboxLabel>
                          <ComboboxCollection>
                            {(project: ProjectInfo) => (
                              <ComboboxItem
                                key={project.id}
                                value={project}
                                title={project.name}
                              >
                                <Text size="sm">{project.name}</Text>
                              </ComboboxItem>
                            )}
                          </ComboboxCollection>
                        </ComboboxGroup>
                      )}
                    </ComboboxList>
                  </ComboboxContent>
                </Combobox>
                {selectProjectMutation.isError && (
                  <Text size="xs" variant="destructive">
                    Couldn't switch to that project. Try again.
                  </Text>
                )}
              </div>
            </motion.div>
          )}
          {(onBack || isAuthenticated) && (
            <StepActions
              primaryAction={
                isAuthenticated ? (
                  <Button
                    size="lg"
                    variant="primary"
                    onClick={() => {
                      track(ANALYTICS_EVENTS.ONBOARDING_PROJECT_SELECTED, {
                        had_multiple_orgs: hasMultipleOrgs,
                        had_multiple_projects: sortedProjects.length > 1,
                      });
                      onNext();
                    }}
                    loading={selectProjectMutation.isPending}
                    disabled={currentProjectId == null || projectLoading}
                  >
                    Continue
                    <ArrowRight size={16} weight="bold" />
                  </Button>
                ) : null
              }
            >
              {onBack && (
                <Button size="lg" variant="outline" onClick={onBack}>
                  <ArrowLeft size={16} weight="bold" />
                  Back
                </Button>
              )}
            </StepActions>
          )}
        </div>
      </div>
    </main>
  );
}
