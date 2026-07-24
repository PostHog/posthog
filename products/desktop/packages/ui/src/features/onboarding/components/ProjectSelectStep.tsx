import {
  ArrowLeft,
  ArrowRight,
  CaretDown,
  CheckCircle,
} from "@phosphor-icons/react";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { happyHog } from "@posthog/ui/assets/hedgehogs";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { SignInCard } from "@posthog/ui/features/auth/SignInCard";
import {
  useAuthStateFetched,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import {
  useSelectProjectMutation,
  useSwitchOrgMutation,
} from "@posthog/ui/features/auth/useAuthMutations";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { StepActions } from "@posthog/ui/features/onboarding/components/StepActions";
import {
  type ProjectInfo,
  useProjects,
} from "@posthog/ui/features/projects/useProjects";
import { OnboardingHogTip } from "@posthog/ui/primitives/OnboardingHogTip";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import {
  FIELD_CONTENT_CLASS,
  FIELD_TRIGGER_CLASS,
} from "@posthog/ui/styles/fieldTrigger";
import { Button, Flex, Spinner, Text } from "@radix-ui/themes";
import { useMutation } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";

const log = logger.scope("project-select-step");

interface Org {
  id: string;
  name: string;
  slug: string;
}

interface ProjectSelectStepProps {
  onNext: () => void;
  onBack: () => void;
}

export function ProjectSelectStep({ onNext, onBack }: ProjectSelectStepProps) {
  const authFetched = useAuthStateFetched();
  const isAuthenticated =
    useAuthStateValue((state) => state.status) === "authenticated";
  const selectProjectMutation = useSelectProjectMutation();
  const currentProjectId = useAuthStateValue((state) => state.currentProjectId);
  const { projects, currentProject } = useProjects();
  const [projectOpen, setProjectOpen] = useState(false);
  const [orgOpen, setOrgOpen] = useState(false);
  const [isSwitchingOrg, setIsSwitchingOrg] = useState(false);
  const orgAnchorRef = useRef<HTMLButtonElement>(null);
  const projectAnchorRef = useRef<HTMLButtonElement>(null);

  const client = useOptionalAuthenticatedClient();
  const { data: fullUser, isLoading } = useCurrentUser({
    client,
  });
  const switchOrgTrpcMutation = useSwitchOrgMutation();

  const organizations = useMemo<Org[]>(() => {
    if (!fullUser?.organizations) return [];
    return fullUser.organizations as Org[];
  }, [fullUser]);

  const currentOrg = fullUser?.organization as
    | { id: string; name: string }
    | undefined;
  const hasMultipleOrgs = organizations.length > 1;

  const sortedOrgs = useMemo(
    () => [...organizations].sort((a, b) => a.name.localeCompare(b.name)),
    [organizations],
  );
  const sortedProjects = useMemo(
    () => [...projects].sort((a, b) => a.name.localeCompare(b.name)),
    [projects],
  );

  const selectedOrg = useMemo(
    () => sortedOrgs.find((o) => o.id === currentOrg?.id) ?? null,
    [sortedOrgs, currentOrg?.id],
  );
  const selectedProject = useMemo(
    () => sortedProjects.find((p) => p.id === currentProjectId) ?? null,
    [sortedProjects, currentProjectId],
  );

  const switchOrgMutation = useMutation({
    mutationFn: async (orgId: string) => {
      await switchOrgTrpcMutation.mutateAsync(orgId);
    },
    onMutate: () => {
      setIsSwitchingOrg(true);
    },
    onError: (err) => {
      setIsSwitchingOrg(false);
      log.error("Failed to switch organization", err);
    },
  });

  useEffect(() => {
    if (isSwitchingOrg && !switchOrgMutation.isPending && !isLoading) {
      setIsSwitchingOrg(false);
    }
  }, [isSwitchingOrg, switchOrgMutation.isPending, isLoading]);

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
            align="start"
            gap="5"
            style={{ margin: "auto 0" }}
            className="w-full"
          >
            {/* Header + form */}
            <Flex direction="column" gap="5" className="w-full">
              {/* Section 1: Sign in */}
              <Flex direction="column" gap="3" className="w-full">
                <AnimatePresence mode="wait">
                  {isAuthenticated ? (
                    <motion.div
                      key="signed-in"
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.2 }}
                    >
                      <Flex direction="column" gap="2">
                        <Text className="font-bold text-(--gray-12) text-2xl">
                          Pick your PostHog home base
                        </Text>
                        <Text className="text-(--gray-11) text-sm">
                          Choose the organization and project you want to work
                          in.
                        </Text>
                      </Flex>
                    </motion.div>
                  ) : authFetched ? (
                    <motion.div
                      key="oauth"
                      initial={{ opacity: 1 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.2 }}
                    >
                      <SignInCard
                        hogSrc={happyHog}
                        hogMessage="I don't bite. Just need to know who I'm working with."
                        subtitle="Connect your account to get started."
                        onAuthInitiated={(region) =>
                          track(ANALYTICS_EVENTS.ONBOARDING_SIGN_IN_INITIATED, {
                            region,
                          })
                        }
                      />
                    </motion.div>
                  ) : null}
                </AnimatePresence>
              </Flex>

              {/* Sections 2+3: Org & project selectors (authenticated only) */}
              {isAuthenticated && (isLoading || isSwitchingOrg) && (
                <Flex align="center" justify="center" className="h-[80px]">
                  <Spinner size="3" />
                </Flex>
              )}

              {isAuthenticated && !isSwitchingOrg && hasMultipleOrgs && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}
                  className="w-full"
                >
                  <Flex direction="column" gap="2" className="w-full">
                    <Text className="font-medium text-(--gray-11) text-sm">
                      Organization
                    </Text>

                    <Combobox<Org>
                      items={sortedOrgs}
                      value={selectedOrg}
                      onValueChange={(value) => {
                        const org = value as Org | null;
                        if (org && org.id !== currentOrg?.id) {
                          switchOrgMutation.mutate(org.id);
                        }
                        setOrgOpen(false);
                      }}
                      open={orgOpen}
                      onOpenChange={setOrgOpen}
                      itemToStringLabel={(org) => org.name}
                      itemToStringValue={(org) => org.id}
                    >
                      <ComboboxTrigger
                        render={
                          <button
                            ref={orgAnchorRef}
                            type="button"
                            className={FIELD_TRIGGER_CLASS}
                          >
                            <Text className="min-w-0 flex-1 truncate text-left font-medium text-(--gray-12)">
                              {currentOrg?.name ?? "Select organization..."}
                            </Text>
                            <CaretDown
                              size={14}
                              className="shrink-0 text-(--gray-9)"
                            />
                          </button>
                        }
                      />
                      <ComboboxContent
                        anchor={orgAnchorRef}
                        side="bottom"
                        align="start"
                        sideOffset={4}
                        className={FIELD_CONTENT_CLASS}
                      >
                        <ComboboxInput
                          placeholder="Search organizations..."
                          showTrigger={false}
                        />
                        <ComboboxEmpty>No organizations found.</ComboboxEmpty>
                        <ComboboxList className="max-h-[240px]">
                          {(org: Org) => (
                            <ComboboxItem
                              key={org.id}
                              value={org}
                              title={org.name}
                            >
                              <Text>{org.name}</Text>
                            </ComboboxItem>
                          )}
                        </ComboboxList>
                      </ComboboxContent>
                    </Combobox>
                  </Flex>
                </motion.div>
              )}

              {/* Section 3: Project selector (only when authenticated, not switching, and loaded) */}
              {isAuthenticated && !isSwitchingOrg && !isLoading && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: 0.05 }}
                  className="w-full"
                >
                  <Flex direction="column" gap="2" className="w-full">
                    <Text className="font-medium text-(--gray-11) text-sm">
                      Project
                    </Text>
                    <Combobox<ProjectInfo>
                      items={sortedProjects}
                      value={selectedProject}
                      onValueChange={(value) => {
                        const project = value as ProjectInfo | null;
                        if (project) {
                          selectProjectMutation.mutate(project.id);
                        }
                        setProjectOpen(false);
                      }}
                      open={projectOpen}
                      onOpenChange={setProjectOpen}
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
                              {currentProject && !hasMultipleOrgs && (
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
                          {(project: ProjectInfo) => (
                            <ComboboxItem
                              key={project.id}
                              value={project}
                              title={project.name}
                            >
                              <Text>{project.name}</Text>
                            </ComboboxItem>
                          )}
                        </ComboboxList>
                      </ComboboxContent>
                    </Combobox>
                  </Flex>
                </motion.div>
              )}

              {/* Signed in confirmation */}
              {isAuthenticated && !isLoading && !isSwitchingOrg && (
                <Flex
                  align="center"
                  gap="2"
                  className="self-start rounded-[8px] border border-(--green-a5) bg-(--green-a2) px-[12px] py-[8px]"
                >
                  <CheckCircle
                    size={16}
                    weight="fill"
                    className="text-(--green-9)"
                  />
                  <Text className="text-(--green-11) text-sm">
                    Signed in as {fullUser?.email}
                  </Text>
                </Flex>
              )}
            </Flex>

            {/* Hog tip */}
            {isAuthenticated && !isLoading && !isSwitchingOrg && (
              <OnboardingHogTip
                hogSrc={happyHog}
                message="I'll use data from this project to help drive product decisions."
              />
            )}
          </Flex>
        </Flex>

        <StepActions>
          <Button size="3" variant="outline" color="gray" onClick={onBack}>
            <ArrowLeft size={16} weight="bold" />
            Back
          </Button>
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
              disabled={currentProjectId == null}
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
