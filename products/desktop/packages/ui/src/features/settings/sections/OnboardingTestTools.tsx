import { Button, Checkbox, Field, FieldLabel, Input } from "@posthog/quill";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToChannelDashboard,
  navigateToChannelTask,
} from "@posthog/ui/router/navigationBridge";
import { type ReactElement, useState } from "react";

function commaSeparated(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function OnboardingTestTools(): ReactElement {
  const client = useAuthenticatedClient();
  const [companyDomain, setCompanyDomain] = useState("");
  const [joiningExistingOrganization, setJoiningExistingOrganization] =
    useState(false);
  const [hasEvents, setHasEvents] = useState(false);
  const [signalReportsWaiting, setSignalReportsWaiting] = useState(0);
  const [otherMembers, setOtherMembers] = useState("");
  const [sourcesEnabled, setSourcesEnabled] = useState("");
  const [sourcesWatching, setSourcesWatching] = useState("");
  const [sourcesNewlyEnabled, setSourcesNewlyEnabled] = useState(false);
  const [includeTeachingCanvas, setIncludeTeachingCanvas] = useState(true);
  const [startingSession, setStartingSession] = useState(false);
  const [creatingCanvas, setCreatingCanvas] = useState(false);

  const startSession = async (): Promise<void> => {
    setStartingSession(true);
    try {
      const result = await client.startOnboardingTestSession({
        company_domain: companyDomain.trim(),
        joining_existing_organization: joiningExistingOrganization,
        has_events: hasEvents,
        signal_reports_waiting: signalReportsWaiting,
        other_members: commaSeparated(otherMembers),
        sources_enabled: commaSeparated(sourcesEnabled),
        sources_watching: commaSeparated(sourcesWatching),
        sources_newly_enabled: sourcesNewlyEnabled,
        include_teaching_canvas: includeTeachingCanvas,
      });
      closeSettings();
      navigateToChannelTask(result.channel_id, result.task_id);
    } catch (error) {
      toast.error("Couldn't start the onboarding test session", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setStartingSession(false);
    }
  };

  const createTeachingCanvas = async (): Promise<void> => {
    setCreatingCanvas(true);
    try {
      const result = await client.createTeachingCanvasForTest();
      closeSettings();
      navigateToChannelDashboard(result.channel_id, result.canvas_id);
    } catch (error) {
      toast.error("Couldn't create the teaching canvas", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setCreatingCanvas(false);
    }
  };

  return (
    <SettingsSection
      label="Onboarding test tools"
      description="Create repeatable first-run experiences from explicit prompt inputs."
    >
      <SettingsCard>
        <div className="grid grid-cols-2 gap-3 p-3.5">
          <Field>
            <FieldLabel htmlFor="onboarding-company-domain">
              Company domain
            </FieldLabel>
            <Input
              id="onboarding-company-domain"
              value={companyDomain}
              onChange={(event) => setCompanyDomain(event.target.value)}
              placeholder="example.com"
              disabled={joiningExistingOrganization || startingSession}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="onboarding-findings">
              Waiting findings
            </FieldLabel>
            <Input
              id="onboarding-findings"
              type="number"
              min={0}
              value={signalReportsWaiting}
              onChange={(event) =>
                setSignalReportsWaiting(Math.max(0, Number(event.target.value)))
              }
              disabled={startingSession}
            />
          </Field>
          <Field className="col-span-2">
            <FieldLabel htmlFor="onboarding-members">Other members</FieldLabel>
            <Input
              id="onboarding-members"
              value={otherMembers}
              onChange={(event) => setOtherMembers(event.target.value)}
              placeholder="Max, Lotte"
              disabled={startingSession}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="onboarding-sources-enabled">
              Enabled sources
            </FieldLabel>
            <Input
              id="onboarding-sources-enabled"
              value={sourcesEnabled}
              onChange={(event) => setSourcesEnabled(event.target.value)}
              placeholder="error tracking, web analytics"
              disabled={startingSession}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="onboarding-sources-watching">
              Watched sources
            </FieldLabel>
            <Input
              id="onboarding-sources-watching"
              value={sourcesWatching}
              onChange={(event) => setSourcesWatching(event.target.value)}
              placeholder="errors, conversion drops"
              disabled={startingSession}
            />
          </Field>
        </div>
        <SettingsCardRow label="Joining an existing organization">
          <Checkbox
            checked={joiningExistingOrganization}
            onCheckedChange={(checked) =>
              setJoiningExistingOrganization(checked === true)
            }
            disabled={startingSession}
          />
        </SettingsCardRow>
        <SettingsCardRow label="Project has events">
          <Checkbox
            checked={hasEvents}
            onCheckedChange={(checked) => setHasEvents(checked === true)}
            disabled={startingSession}
          />
        </SettingsCardRow>
        <SettingsCardRow label="Sources newly enabled">
          <Checkbox
            checked={sourcesNewlyEnabled}
            onCheckedChange={(checked) =>
              setSourcesNewlyEnabled(checked === true)
            }
            disabled={startingSession}
          />
        </SettingsCardRow>
        <SettingsCardRow label="Include teaching canvas in the prompt">
          <Checkbox
            checked={includeTeachingCanvas}
            onCheckedChange={(checked) =>
              setIncludeTeachingCanvas(checked === true)
            }
            disabled={startingSession}
          />
        </SettingsCardRow>
        <SettingsCardRow
          label="First-run session"
          description="Creates a new session every time and opens it in #general."
        >
          <Button
            variant="primary"
            size="sm"
            loading={startingSession}
            disabled={creatingCanvas}
            onClick={() => void startSession()}
          >
            Start session
          </Button>
        </SettingsCardRow>
        <SettingsCardRow
          label="Teaching canvas"
          description="Creates or repairs the canvas, then opens it."
        >
          <Button
            variant="outline"
            size="sm"
            loading={creatingCanvas}
            disabled={startingSession}
            onClick={() => void createTeachingCanvas()}
          >
            Create canvas
          </Button>
        </SettingsCardRow>
      </SettingsCard>
    </SettingsSection>
  );
}
