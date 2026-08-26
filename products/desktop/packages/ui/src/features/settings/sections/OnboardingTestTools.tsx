import { Button } from "@posthog/quill";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { leaveSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { OnboardingTestToolsDialog } from "@posthog/ui/features/settings/sections/OnboardingTestToolsDialog";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToChannelDashboard } from "@posthog/ui/router/navigationBridge";
import { type ReactElement, useState } from "react";

export function OnboardingTestTools(): ReactElement {
  const client = useAuthenticatedClient();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [creatingCanvas, setCreatingCanvas] = useState(false);

  const createTeachingCanvas = async (): Promise<void> => {
    setCreatingCanvas(true);
    try {
      const result = await client.createTeachingCanvasForTest();
      leaveSettings();
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
    <SettingsSection label="Onboarding test tools">
      <SettingsCard>
        <SettingsCardRow
          label="First-run session"
          description="Describe who's arriving, then open a session built from those answers."
        >
          <Button
            variant="outline"
            size="sm"
            onClick={() => setWizardOpen(true)}
          >
            Set up
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
            onClick={() => void createTeachingCanvas()}
          >
            Create canvas
          </Button>
        </SettingsCardRow>
      </SettingsCard>

      <OnboardingTestToolsDialog
        open={wizardOpen}
        onOpenChange={setWizardOpen}
      />
    </SettingsSection>
  );
}
