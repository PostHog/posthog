import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { Button, Text } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  authKeys,
  useCurrentUser,
} from "@posthog/ui/features/auth/useCurrentUser";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { desktopBetaTermsKeys, type OrgConsent } from "./useOrgConsent";

interface ConsentPanelProps {
  consent: Extract<OrgConsent, { status: "resolved" }>;
  isAdmin: boolean;
  onSubmittingChange?: (isSubmitting: boolean) => void;
}

export function ConsentPanel({
  consent,
  isAdmin,
  onSubmittingChange,
}: ConsentPanelProps) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const { data: currentUser } = useCurrentUser({
    client,
    refetchOnWindowFocus: "always",
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const organization = currentUser?.organization;

  const submit = async (): Promise<void> => {
    if (!organization || isSubmitting) return;
    setError(null);
    setIsSubmitting(true);
    onSubmittingChange?.(true);

    const requests: Array<{
      kind: "ai" | "beta";
      request: Promise<void>;
    }> = [];
    if (consent.needsAiConsent) {
      requests.push({
        kind: "ai",
        request: client.approveAiDataProcessing(organization.id),
      });
    }
    if (consent.needsBetaTerms) {
      requests.push({
        kind: "beta",
        request: client.acceptDesktopBetaTerms(organization.id),
      });
    }

    const results = await Promise.allSettled(
      requests.map(({ request }) => request),
    );
    const confirmations: Promise<unknown>[] = [];
    results.forEach((result, index) => {
      if (result.status !== "fulfilled") return;
      if (requests[index].kind === "ai") {
        track(ANALYTICS_EVENTS.AI_CONSENT_GRANTED_INAPP);
        confirmations.push(
          queryClient.invalidateQueries({ queryKey: authKeys.currentUsers() }),
        );
      } else {
        track(ANALYTICS_EVENTS.DESKTOP_BETA_TERMS_ACCEPTED_INAPP);
        confirmations.push(
          queryClient.invalidateQueries({
            queryKey: desktopBetaTermsKeys.all(),
          }),
        );
      }
    });
    await Promise.allSettled(confirmations);

    if (results.some((result) => result.status === "rejected")) {
      setError(
        "Some organization consent updates could not be saved. Try again or contact support.",
      );
    }
    setIsSubmitting(false);
    onSubmittingChange?.(false);
  };

  return (
    <div className="flex w-full max-w-[600px] flex-col gap-5">
      <div className="flex flex-col gap-2">
        <h1 className="font-bold text-2xl text-foreground">
          Review organization consent
        </h1>
        <Text size="sm" variant="muted">
          {organization?.name
            ? `Review the remaining terms for ${organization.name}.`
            : "Review the remaining terms for your organization."}
        </Text>
      </div>

      {consent.satisfied && (
        <div className="flex gap-3 rounded-lg border border-success/40 bg-success/10 p-4 text-foreground text-sm">
          <CheckCircle className="mt-0.5 shrink-0 text-success" size={18} />
          <div>
            <p className="font-semibold">Organization consent complete</p>
            <p className="mt-1 text-muted-foreground">
              Your organization has accepted the required terms.
            </p>
          </div>
        </div>
      )}

      {consent.needsAiConsent && (
        <section className="flex flex-col gap-2 rounded-lg border border-border bg-surface-primary p-4">
          <h2 className="font-semibold text-base text-foreground">
            AI data processing
          </h2>
          <Text size="sm" variant="muted">
            PostHog AI features process identifying user data with external AI
            providers. These providers do not use your data to train models.
          </Text>
        </section>
      )}

      {consent.needsBetaTerms && (
        <section className="flex flex-col gap-2 rounded-lg border border-border bg-surface-primary p-4">
          <h2 className="font-semibold text-base text-foreground">
            PostHog Desktop beta terms
          </h2>
          <Text size="sm" variant="muted">
            PostHog Desktop uses Baseten and Modal to process customer data,
            personal data, and PII. They are not currently listed as PostHog
            subprocessors for this feature.
          </Text>
          <Text size="sm" variant="muted">
            Your organization agrees to proceed notwithstanding that status. If
            this feature becomes generally available, PostHog will update the
            DPA and provide notice. This beta may change or be discontinued.
          </Text>
          <a
            href="https://posthog.com/subprocessors"
            target="_blank"
            rel="noreferrer"
            className="text-link text-sm hover:underline"
          >
            View PostHog subprocessors
          </a>
        </section>
      )}

      <div className="flex gap-3 rounded-lg border border-warning/40 bg-warning/10 p-4 text-foreground text-sm">
        <WarningCircle className="mt-0.5 shrink-0" size={18} />
        <div>
          <p className="font-semibold">Protected Health Information</p>
          <p className="mt-1 text-muted-foreground">
            PostHog Desktop is not HIPAA-compliant and is not intended for
            processing Protected Health Information (PHI). A Business Associate
            Agreement with PostHog does not currently apply to PostHog Desktop.
          </p>
        </div>
      </div>

      {consent.satisfied ? null : isAdmin ? (
        <Button
          variant="primary"
          size="lg"
          className="w-full"
          loading={isSubmitting}
          disabled={isSubmitting || !organization}
          onClick={() => void submit()}
        >
          Accept and continue
        </Button>
      ) : (
        <Text size="sm" variant="muted">
          Ask an organization admin to accept these terms.
        </Text>
      )}

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-destructive-foreground text-sm">
          {error}
        </div>
      )}
    </div>
  );
}
