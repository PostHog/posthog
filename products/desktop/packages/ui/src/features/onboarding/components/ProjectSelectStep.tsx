import {
  ArrowLeft,
  ArrowRight,
  CaretDown,
  CheckCircle,
} from "@phosphor-icons/react";
import {
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
} from "@posthog/quill";
import { REGION_LABELS } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { OAuthControls } from "@posthog/ui/features/auth/OAuthControls";
import {
  useAuthStateFetched,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useSelectProjectMutation } from "@posthog/ui/features/auth/useAuthMutations";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { StepActions } from "@posthog/ui/features/onboarding/components/StepActions";
import {
  type ProjectInfo,
  useProjects,
} from "@posthog/ui/features/projects/useProjects";
import { ProductWordmark } from "@posthog/ui/primitives/ProductWordmark";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import {
  FIELD_CONTENT_CLASS,
  FIELD_TRIGGER_CLASS,
} from "@posthog/ui/styles/fieldTrigger";
import { Button, Flex, Spinner, Text } from "@radix-ui/themes";
import { AnimatePresence, motion } from "framer-motion";
import { useMemo, useRef, useState } from "react";

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

/** The sign-in button resolves into this, so signing in reads as a completed line. */
function SignedInRow({ email }: { email: string | undefined }) {
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const region = cloudRegion ? REGION_LABELS[cloudRegion].label : null;
  return (
    <Flex
      align="center"
      gap="2"
      className="h-[44px] w-full rounded-[6px] border border-(--gray-a4) px-[14px]"
    >
      <CheckCircle
        size={16}
        weight="fill"
        className="shrink-0 text-(--green-9)"
      />
      <Text className="min-w-0 truncate text-(--gray-12) text-sm">
        Signed in as {email ?? "your PostHog account"}
      </Text>
      {region && (
        <Text className="ml-auto shrink-0 text-(--gray-11) text-xs">
          {region}
        </Text>
      )}
    </Flex>
  );
}

export function ProjectSelectStep({ onNext, onBack }: ProjectSelectStepProps) {
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

  return (
    <Flex align="center" justify="center" height="100%" px="8">
      <Flex
        direction="column"
        align="center"
        className="h-full w-full max-w-[480px] pt-[24px] pb-[40px]"
      >
        <Flex
          direction="column"
          align="center"
          className="min-h-0 w-full flex-1 overflow-y-auto"
        >
          <Flex
            direction="column"
            gap="6"
            style={{ margin: "auto 0" }}
            className="w-full"
          >
            <div className="flex justify-center">
              <ProductWordmark />
            </div>

            <AnimatePresence mode="wait">
              {isAuthenticated ? (
                <motion.div
                  key="signed-in"
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2 }}
                  className="w-full"
                >
                  <SignedInRow email={fullUser?.email} />
                </motion.div>
              ) : authFetched ? (
                <motion.div
                  key="oauth"
                  initial={{ opacity: 1 }}
                  exit={{ opacity: 0, y: -4 }}
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

            {isAuthenticated && isLoading && (
              <Flex align="center" justify="center" className="h-[80px]">
                <Spinner size="3" />
              </Flex>
            )}

            {isAuthenticated && !isLoading && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
                className="w-full"
              >
                <Flex direction="column" gap="2" className="w-full">
                  <Text className="font-medium text-(--gray-11) text-sm">
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
                    disabled={selectProjectMutation.isPending}
                    itemToStringLabel={(project) => project.name}
                    itemToStringValue={(project) => String(project.id)}
                  >
                    <ComboboxTrigger
                      render={
                        <button
                          ref={projectAnchorRef}
                          type="button"
                          className={FIELD_TRIGGER_CLASS}
                        >
                          <Flex
                            direction="column"
                            gap="1"
                            align="start"
                            className="min-w-0 flex-1 text-left"
                          >
                            <Text className="min-w-0 max-w-full truncate font-medium text-(--gray-12)">
                              {currentProject?.name ?? "Select a project..."}
                            </Text>
                            {currentProject && (
                              <Text className="min-w-0 max-w-full truncate text-(--gray-11) text-[13px]">
                                {currentProject.organization.name}
                              </Text>
                            )}
                          </Flex>
                          <CaretDown
                            size={14}
                            className="shrink-0 text-(--gray-9)"
                          />
                        </button>
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
                                  <Text>{project.name}</Text>
                                </ComboboxItem>
                              )}
                            </ComboboxCollection>
                          </ComboboxGroup>
                        )}
                      </ComboboxList>
                    </ComboboxContent>
                  </Combobox>
                  {selectProjectMutation.isError && (
                    <Text className="text-(--red-11) text-[13px]">
                      Couldn't switch to that project. Try again.
                    </Text>
                  )}
                </Flex>
              </motion.div>
            )}
          </Flex>
        </Flex>

        <StepActions>
          {onBack && (
            <Button size="3" variant="outline" color="gray" onClick={onBack}>
              <ArrowLeft size={16} weight="bold" />
              Back
            </Button>
          )}
          {isAuthenticated && !isLoading && (
            <Button
              size="3"
              onClick={() => {
                track(ANALYTICS_EVENTS.ONBOARDING_PROJECT_SELECTED, {
                  had_multiple_orgs: hasMultipleOrgs,
                  had_multiple_projects: sortedProjects.length > 1,
                });
                onNext();
              }}
              loading={selectProjectMutation.isPending}
              disabled={
                currentProjectId == null || selectProjectMutation.isPending
              }
            >
              Continue
              <ArrowRight size={16} weight="bold" />
            </Button>
          )}
        </StepActions>
      </Flex>
    </Flex>
  );
}
