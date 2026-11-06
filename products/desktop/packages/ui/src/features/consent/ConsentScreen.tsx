import { GearSix, Lifebuoy, SignOut } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { useLogoutMutation } from "@posthog/ui/features/auth/useAuthMutations";
import { useIsOrgAdmin } from "@posthog/ui/features/auth/useOrgRole";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { openSettingsDialog } from "@posthog/ui/features/settings/SettingsDialog";
import { ProjectSwitcher } from "@posthog/ui/features/sidebar/components/ProjectSwitcher";
import { FullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import type { ReactNode } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { ConsentErrorContent } from "./ConsentErrorContent";
import { ConsentPanel } from "./ConsentPanel";
import { useOrgConsent } from "./useOrgConsent";

interface ConsentScreenProps {
  banner?: ReactNode;
  onOpenSupport?: () => void;
  settingsDialog?: ReactNode;
}

export function ConsentScreen({
  banner,
  onOpenSupport,
  settingsDialog,
}: ConsentScreenProps) {
  const consent = useOrgConsent();
  const { isAdmin } = useIsOrgAdmin();
  const logoutMutation = useLogoutMutation();
  useHotkeys(SHORTCUTS.SETTINGS, () => openSettingsDialog(), {
    preventDefault: true,
    enableOnFormTags: true,
  });

  const footerLeft = (
    <div className="flex items-center gap-3">
      <Button
        variant="link-muted"
        size="xs"
        onClick={() => openSettingsDialog()}
      >
        <GearSix size={14} />
        Settings
      </Button>
      <Button variant="link-muted" size="xs" onClick={onOpenSupport}>
        <Lifebuoy size={14} />
        Get support
      </Button>
      {banner}
    </div>
  );
  const footerRight = (
    <Button
      variant="link-muted"
      size="xs"
      loading={logoutMutation.isPending}
      onClick={() => logoutMutation.mutate()}
    >
      <SignOut size={14} />
      Log out
    </Button>
  );

  return (
    <>
      <FullScreenLayout footerLeft={footerLeft} footerRight={footerRight}>
        <div className="flex h-full flex-col overflow-y-auto px-8 pt-12 pb-16">
          <div className="flex shrink-0 justify-end">
            <div className="w-64 max-w-full">
              <ProjectSwitcher />
            </div>
          </div>
          <div className="flex min-h-0 flex-1 items-center justify-center py-8">
            {consent.status === "error" ? (
              <ConsentErrorContent onRetry={consent.retry} />
            ) : consent.status === "resolved" ? (
              <ConsentPanel consent={consent} isAdmin={isAdmin === true} />
            ) : null}
          </div>
        </div>
      </FullScreenLayout>
      {settingsDialog}
    </>
  );
}
