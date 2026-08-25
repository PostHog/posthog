import {
  ArrowClockwise,
  CaretDown,
  Coins,
  Key,
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
  Input,
  Spinner,
} from "@posthog/quill";
import { FullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import {
  FIELD_CONTENT_CLASS,
  FIELD_TRIGGER_CLASS,
} from "@posthog/ui/styles/fieldTrigger";
import { useMemo, useRef, useState } from "react";

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
    description:
      "Organizations in the Startup or YC program can't use PostHog Desktop. Select another organization to continue.",
  },
  prepaid_credits: {
    icon: <Coins />,
    title: "Desktop isn't available with prepaid credits",
    description:
      "Organizations with pending or active prepaid credits can't use PostHog Desktop. Select another organization to continue. To discuss access, contact your PostHog account executive. If you don't have one, email sales@posthog.com.",
  },
} as const;

interface DesktopAccessScreenProps {
  access: DesktopAccess;
  orgProjectsMap: OrgProjectsMap;
  currentOrgId: string | null;
  currentProjectId: number | null;
  isSwitching: boolean;
  isRetrying: boolean;
  isRedeemingInviteCode: boolean;
  isLoggingOut: boolean;
  switchError: string | null;
  redemptionError: string | null;
  onSelectOrganization: (organizationId: string) => void;
  onSelectProject: (projectId: number) => void;
  onRedeemInviteCode: (inviteCode: string) => void;
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
  isRedeemingInviteCode,
  isLoggingOut,
  switchError,
  redemptionError,
  onSelectOrganization,
  onSelectProject,
  onRedeemInviteCode,
  onRetry,
  onLogout,
  onOpenSupport,
}: DesktopAccessScreenProps) {
  const [organizationOpen, setOrganizationOpen] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);
  const [inviteCode, setInviteCode] = useState("");
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
  const controlsDisabled =
    isSwitching || isRedeemingInviteCode || access.status === "checking";
  const isLegacyAccessRequired =
    access.status === "blocked" && access.reason === null;

  const blockedContent = access.reason
    ? BLOCKED_CONTENT[access.reason]
    : {
        icon: <Key />,
        title: "Enter your invite code",
        description:
          "This organization needs an invite code to use PostHog Desktop. Enter one below or select another organization.",
      };
  const isTechnicalError = access.status === "error";
  const icon = isTechnicalError ? <WarningCircle /> : blockedContent?.icon;
  const title = isTechnicalError
    ? "Couldn't check Desktop access"
    : blockedContent?.title;
  const description = isTechnicalError
    ? "Try again, or select another organization or project."
    : blockedContent?.description;

  const footerRight = (
    <Button
      variant="link-muted"
      size="sm"
      loading={isLoggingOut}
      disabled={
        isLoggingOut || isSwitching || isRetrying || isRedeemingInviteCode
      }
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
              {isLegacyAccessRequired && (
                <form
                  className="flex w-full flex-col gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    onRedeemInviteCode(inviteCode.trim());
                  }}
                >
                  <Field>
                    <FieldLabel htmlFor="desktop-access-invite-code">
                      Invite code
                    </FieldLabel>
                    <Input
                      id="desktop-access-invite-code"
                      value={inviteCode}
                      onChange={(event) =>
                        setInviteCode(event.currentTarget.value)
                      }
                      disabled={isRedeemingInviteCode || isSwitching}
                      autoComplete="off"
                    />
                  </Field>
                  {redemptionError && (
                    <p role="alert" className="text-destructive text-sm">
                      {redemptionError}
                    </p>
                  )}
                  <Button
                    type="submit"
                    variant="primary"
                    loading={isRedeemingInviteCode}
                    disabled={
                      isRedeemingInviteCode ||
                      isSwitching ||
                      inviteCode.trim().length === 0
                    }
                    data-attr="desktop-access-redeem-invite-code"
                  >
                    Redeem invite code
                  </Button>
                </form>
              )}

              <div className="flex w-full flex-col gap-4">
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
              </div>

              {switchError && (
                <p role="alert" className="text-destructive text-sm">
                  {switchError}
                </p>
              )}

              {!isLegacyAccessRequired && (
                <Button
                  variant="primary"
                  loading={isRetrying}
                  disabled={isRetrying || isSwitching}
                  onClick={onRetry}
                  data-attr="desktop-access-retry"
                >
                  <ArrowClockwise />
                  {isTechnicalError ? "Try again" : "Check again"}
                </Button>
              )}
            </EmptyContent>
          </Empty>
        </div>
      </div>
    </FullScreenLayout>
  );
}
