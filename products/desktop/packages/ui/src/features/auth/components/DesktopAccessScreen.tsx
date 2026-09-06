import {
  ArrowClockwise,
  CaretDown,
  Coins,
  Lifebuoy,
  RocketLaunch,
  SignOut,
  WarningCircle,
} from "@phosphor-icons/react";
import type { DesktopAccess, OrgProjectsMap } from "@posthog/core/auth/schemas";
import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Field,
  FieldLabel,
  Spinner,
} from "@posthog/quill";
import { useDesktopAccessAnalytics } from "@posthog/ui/features/auth/desktopAccessAnalytics";
import { FullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import {
  FIELD_CONTENT_CLASS,
  FIELD_TRIGGER_CLASS,
} from "@posthog/ui/styles/fieldTrigger";
import { useEffect, useMemo, useRef, useState } from "react";

interface OrganizationOption {
  id: string;
  name: string;
}

interface ProjectOption {
  id: number;
  name: string;
}

const BLOCKED_CONTENT = {
  startup_plan: {
    icon: <RocketLaunch />,
    title: "Desktop isn't available for this organization",
    reason:
      "Organizations in the Startup or YC program can't use PostHog Desktop.",
    noAlternative:
      "This is the only organization on your account. Get in touch to ask about access.",
    contact: "",
  },
  prepaid_credits: {
    icon: <Coins />,
    title: "Desktop isn't available with prepaid credits",
    reason:
      "Organizations with pending or active prepaid credits can't use PostHog Desktop.",
    noAlternative: "This is the only organization on your account.",
    contact:
      "To ask about access, contact your PostHog account executive. If you don't have one, email sales@posthog.com.",
  },
} as const;

const UNKNOWN_BLOCK_CONTENT = {
  icon: <WarningCircle />,
  title: "Desktop isn't available for this organization",
  reason: "",
  noAlternative:
    "This is the only organization on your account. Get in touch to ask about access.",
  contact: "",
} as const;

const SWITCH_ORGANIZATION_HINT = "Select another organization to continue.";

interface DesktopAccessScreenProps {
  access: DesktopAccess;
  orgProjectsMap: OrgProjectsMap;
  currentOrgId: string | null;
  currentProjectId: number | null;
  isSwitching: boolean;
  isRetrying: boolean;
  isLoggingOut: boolean;
  switchError: string | null;
  onSelectOrganization: (organizationId: string) => void;
  onSelectProject: (projectId: number) => void;
  onRetry: () => void;
  onLogout: () => void;
  onOpenSupport: () => void;
}

export function DesktopAccessScreen({
  access,
  orgProjectsMap,
  currentOrgId,
  currentProjectId,
  isSwitching,
  isRetrying,
  isLoggingOut,
  switchError,
  onSelectOrganization,
  onSelectProject,
  onRetry,
  onLogout,
  onOpenSupport,
}: DesktopAccessScreenProps) {
  const [organizationOpen, setOrganizationOpen] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);
  const organizationAnchorRef = useRef<HTMLButtonElement>(null);
  const projectAnchorRef = useRef<HTMLButtonElement>(null);

  const organizations = useMemo<OrganizationOption[]>(
    () =>
      Object.entries(orgProjectsMap)
        .map(([id, organization]) => ({ id, name: organization.orgName }))
        .sort((first, second) => first.name.localeCompare(second.name)),
    [orgProjectsMap],
  );
  const projects = useMemo<ProjectOption[]>(
    () =>
      (currentOrgId
        ? (orgProjectsMap[currentOrgId]?.projects ?? [])
        : []
      ).toSorted((first, second) => first.name.localeCompare(second.name)),
    [currentOrgId, orgProjectsMap],
  );
  const selectedOrganization =
    organizations.find((organization) => organization.id === currentOrgId) ??
    null;
  const selectedProject =
    projects.find((project) => project.id === currentProjectId) ?? null;
  const controlsDisabled = isSwitching || access.status === "checking";

  const hasOtherOrganizations = organizations.some(
    (organization) => organization.id !== currentOrgId,
  );
  const isTechnicalError = access.status === "error";
  const showOrganizationPicker = organizations.length > 1;
  const blockedContent = access.reason
    ? BLOCKED_CONTENT[access.reason]
    : UNKNOWN_BLOCK_CONTENT;
  const icon = isTechnicalError ? <WarningCircle /> : blockedContent.icon;
  const title = isTechnicalError
    ? "Couldn't check Desktop access"
    : blockedContent.title;
  const description = isTechnicalError
    ? showOrganizationPicker
      ? "Try again, or select another organization or project."
      : "Try again, or select another project."
    : [
        blockedContent.reason,
        hasOtherOrganizations
          ? SWITCH_ORGANIZATION_HINT
          : blockedContent.noAlternative,
        blockedContent.contact,
      ]
        .filter(Boolean)
        .join(" ");
  const supportIsPrimary = !isTechnicalError && !hasOtherOrganizations;
  const unchangedRechecks = useUnchangedRechecks(isRetrying, access);
  useDesktopAccessAnalytics(access, hasOtherOrganizations, unchangedRechecks);

  const footerRight = (
    <Button
      variant="link-muted"
      size="sm"
      loading={isLoggingOut}
      disabled={isLoggingOut || isSwitching || isRetrying}
      onClick={onLogout}
      data-attr="desktop-access-logout"
    >
      <SignOut />
      Log out
    </Button>
  );

  return (
    <FullScreenLayout footerRight={footerRight} onOpenSupport={onOpenSupport}>
      <div className="h-full overflow-y-auto px-8 py-20">
        <div className="flex min-h-full items-center justify-center">
          <Empty className="w-full max-w-xl">
            <EmptyHeader>
              <EmptyMedia variant="icon">{icon}</EmptyMedia>
              <EmptyTitle>{title}</EmptyTitle>
              <EmptyDescription>{description}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="w-full max-w-md gap-4">
              {(showOrganizationPicker || isTechnicalError) && (
                <div className="flex w-full flex-col gap-4">
                  {showOrganizationPicker && (
                    <Field className="min-w-0">
                      <FieldLabel htmlFor="desktop-access-organization">
                        Organization
                      </FieldLabel>
                      <Combobox<OrganizationOption>
                        items={organizations}
                        value={selectedOrganization}
                        onValueChange={(value) => {
                          if (value && value.id !== currentOrgId) {
                            onSelectOrganization(value.id);
                          }
                          setOrganizationOpen(false);
                        }}
                        open={organizationOpen}
                        onOpenChange={setOrganizationOpen}
                        itemToStringLabel={(organization) => organization.name}
                        itemToStringValue={(organization) => organization.id}
                        disabled={controlsDisabled}
                      >
                        <ComboboxTrigger
                          nativeButton
                          render={
                            <button
                              ref={organizationAnchorRef}
                              id="desktop-access-organization"
                              type="button"
                              className={FIELD_TRIGGER_CLASS}
                              data-attr="desktop-access-organization-switcher"
                            >
                              <span className="min-w-0 flex-1 truncate text-left">
                                {selectedOrganization?.name ??
                                  "Select organization"}
                              </span>
                              {isSwitching ? (
                                <Spinner />
                              ) : (
                                <CaretDown
                                  size={14}
                                  className="shrink-0 text-muted"
                                />
                              )}
                            </button>
                          }
                        />
                        <ComboboxContent
                          anchor={organizationAnchorRef}
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
                          <ComboboxList>
                            {(organization: OrganizationOption) => (
                              <ComboboxItem
                                key={organization.id}
                                value={organization}
                              >
                                {organization.name}
                              </ComboboxItem>
                            )}
                          </ComboboxList>
                        </ComboboxContent>
                      </Combobox>
                    </Field>
                  )}

                  {/* The answer covers the whole organization, so another
                project inside it gets the same one. Only a failed check turns
                on the project, because a check with no project fails. */}
                  {isTechnicalError && (
                    <Field className="min-w-0">
                      <FieldLabel htmlFor="desktop-access-project">
                        Project
                      </FieldLabel>
                      <Combobox<ProjectOption>
                        items={projects}
                        value={selectedProject}
                        onValueChange={(value) => {
                          if (value && value.id !== currentProjectId) {
                            onSelectProject(value.id);
                          }
                          setProjectOpen(false);
                        }}
                        open={projectOpen}
                        onOpenChange={setProjectOpen}
                        itemToStringLabel={(project) => project.name}
                        itemToStringValue={(project) => String(project.id)}
                        disabled={controlsDisabled}
                      >
                        <ComboboxTrigger
                          nativeButton
                          render={
                            <button
                              ref={projectAnchorRef}
                              id="desktop-access-project"
                              type="button"
                              className={FIELD_TRIGGER_CLASS}
                              data-attr="desktop-access-project-switcher"
                            >
                              <span className="min-w-0 flex-1 truncate text-left">
                                {selectedProject?.name ?? "Select project"}
                              </span>
                              {isSwitching ? (
                                <Spinner />
                              ) : (
                                <CaretDown
                                  size={14}
                                  className="shrink-0 text-muted"
                                />
                              )}
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
                          <ComboboxList>
                            {(project: ProjectOption) => (
                              <ComboboxItem key={project.id} value={project}>
                                {project.name}
                              </ComboboxItem>
                            )}
                          </ComboboxList>
                        </ComboboxContent>
                      </Combobox>
                    </Field>
                  )}
                </div>
              )}

              {switchError && (
                <p role="alert" className="text-destructive text-sm">
                  {switchError}
                </p>
              )}

              <div className="flex flex-wrap items-center justify-center gap-2">
                {supportIsPrimary && (
                  <Button
                    variant="primary"
                    onClick={onOpenSupport}
                    data-attr="desktop-access-support"
                  >
                    <Lifebuoy />
                    Get in touch
                  </Button>
                )}
                <Button
                  variant={supportIsPrimary ? "outline" : "primary"}
                  loading={isRetrying}
                  disabled={isRetrying || isSwitching}
                  onClick={onRetry}
                  data-attr="desktop-access-retry"
                >
                  <ArrowClockwise />
                  {isTechnicalError ? "Try again" : "Check again"}
                </Button>
              </div>

              {!isTechnicalError && unchangedRechecks > 0 && (
                <output className="text-(--gray-12) text-sm">
                  We checked again and nothing changed. Get in touch if you
                  think this is wrong.
                </output>
              )}
            </EmptyContent>
          </Empty>
        </div>
      </div>
    </FullScreenLayout>
  );
}

/**
 * How many rechecks came back with the same answer. The blocked reason only
 * changes when billing changes, so the button looks broken without this: the
 * screen is identical before and after the check, and people keep clicking it.
 */
function useUnchangedRechecks(
  isRetrying: boolean,
  access: DesktopAccess,
): number {
  const answerKey = `${access.status}:${access.reason}:${access.projectId}`;
  const previous = useRef({ isRetrying, answerKey });
  const [rechecks, setRechecks] = useState(0);

  useEffect(() => {
    const wasRetrying = previous.current.isRetrying;
    const answerChanged = previous.current.answerKey !== answerKey;
    previous.current = { isRetrying, answerKey };
    if (answerChanged) {
      setRechecks(0);
      return;
    }
    if (wasRetrying && !isRetrying) {
      setRechecks((count) => count + 1);
    }
  }, [isRetrying, answerKey]);

  return rechecks;
}
