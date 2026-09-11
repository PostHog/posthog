import { ShieldWarning } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import { logger } from "../../../shell/logger";
import { useAuthStateValue } from "../store";
import { useLoginMutation, useLogoutMutation } from "../useAuthMutations";

const log = logger.scope("scope-reauth-prompt");

export function ScopeReauthPrompt() {
  const needsScopeReauth = useAuthStateValue((state) => state.needsScopeReauth);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const loginMutation = useLoginMutation();
  const logoutMutation = useLogoutMutation();

  const handleSignIn = async () => {
    if (!cloudRegion) {
      log.warn("Cannot re-authenticate: no cloud region available");
      return;
    }

    try {
      await loginMutation.mutateAsync(cloudRegion);
    } catch (error) {
      log.error("Re-authentication failed", error);
    }
  };

  return (
    <AlertDialog open={needsScopeReauth}>
      <AlertDialogContent className="max-w-[360px]">
        <AlertDialogHeader>
          <AlertDialogTitle>
            <span className="flex items-center gap-2">
              <ShieldWarning weight="bold" />
              Re-authentication required
            </span>
          </AlertDialogTitle>
          <AlertDialogDescription>
            PostHog has been updated with new features that require additional
            permissions. Please sign in again to continue.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="sm:justify-between">
          <Button
            type="button"
            variant="outline"
            onClick={() => logoutMutation.mutate()}
            loading={logoutMutation.isPending}
            disabled={loginMutation.isPending}
          >
            Log out
          </Button>
          <Button
            type="button"
            variant="primary"
            onClick={handleSignIn}
            loading={loginMutation.isPending}
            disabled={!cloudRegion || logoutMutation.isPending}
          >
            Sign in
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
