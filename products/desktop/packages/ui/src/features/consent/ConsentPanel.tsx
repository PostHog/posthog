import { CheckCircle } from "@phosphor-icons/react";
import {
  Badge,
  Button,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Text,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  authKeys,
  useCurrentUser,
} from "@posthog/ui/features/auth/useCurrentUser";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
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
  const [submitting, setSubmitting] = useState<"ai" | "beta" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const organization = currentUser?.organization;

  const accept = async (kind: "ai" | "beta"): Promise<void> => {
    if (!organization || submitting) return;
    setError(null);
    setSubmitting(kind);
    onSubmittingChange?.(true);

    try {
      if (kind === "ai") {
        await client.approveAiDataProcessing(organization.id);
        track(ANALYTICS_EVENTS.AI_CONSENT_GRANTED_INAPP);
        await queryClient.invalidateQueries({
          queryKey: authKeys.currentUsers(),
        });
      } else {
        await client.acceptDesktopBetaTerms(organization.id);
        track(ANALYTICS_EVENTS.DESKTOP_BETA_TERMS_ACCEPTED_INAPP);
        await queryClient.invalidateQueries({
          queryKey: desktopBetaTermsKeys.all(),
        });
      }
    } catch {
      setError(
        kind === "ai"
          ? "Could not approve AI data processing. Try again or contact support."
          : "Desktop beta terms acceptance could not be saved. Try again or contact support.",
      );
    } finally {
      setSubmitting(null);
      onSubmittingChange?.(false);
    }
  };

  return (
    <div className="flex w-full max-w-[560px] flex-col gap-5">
      <div className="flex flex-col gap-2">
        <h1 className="font-bold text-2xl text-foreground tracking-[-0.02em]">
          Before you continue
        </h1>
        <Text size="sm" variant="muted">
          {organization?.name
            ? `${organization.name} needs to review the items below.`
            : "Your organization needs to review the items below."}
        </Text>
      </div>

      {consent.satisfied && (
        <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-primary px-4 py-3">
          <CheckCircle className="shrink-0 text-success-foreground" size={20} />
          <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
            <Text weight="semibold">Organization consent complete</Text>
            <Badge variant="completed">Accepted</Badge>
          </div>
        </div>
      )}

      {consent.needsAiConsent && (
        <ConsentDecision
          title="PostHog AI needs your approval"
          summary={
            organization?.name ? (
              <>
                Your "<strong>{organization.name}</strong>" organization hasn't
                approved AI data processing yet.
              </>
            ) : (
              "Your organization hasn't approved AI data processing yet."
            )
          }
          actionLabel="Approve AI data processing"
          adminHelp="Ask an organization admin to approve AI data processing."
          isAdmin={isAdmin}
          isLoading={submitting === "ai"}
          isDisabled={submitting !== null || !organization}
          onAccept={() => void accept("ai")}
        >
          <div className="flex flex-col gap-3">
            <Text size="sm" variant="muted">
              PostHog AI features process identifying user data with external AI
              providers.
              <br />
              Importantly: Your data won't be used for training models by these
              providers.
            </Text>
            <div>
              <Text size="sm" weight="semibold">
                Legal bits about Protected Health Information
              </Text>
              <Text className="mt-1" size="sm" variant="muted">
                This app isn't <i>yet</i> HIPAA-compliant and is not intended
                for processing of Protected Health Information ("PHI").
                <br />
                If you've entered into a Business Associate Agreement ("BAA")
                with PostHog, it does not currently apply to PostHog Code
                features.
              </Text>
            </div>
          </div>
        </ConsentDecision>
      )}

      {consent.needsBetaTerms && (
        <ConsentDecision
          title="PostHog Desktop beta terms"
          summary="Accept the additional data-processing terms for the PostHog Desktop beta."
          actionLabel="Accept beta terms"
          adminHelp="Ask an organization admin to accept the Desktop beta terms."
          isAdmin={isAdmin}
          isLoading={submitting === "beta"}
          isDisabled={submitting !== null || !organization}
          onAccept={() => void accept("beta")}
        >
          <div className="flex flex-col gap-2">
            <Text size="sm" variant="muted">
              PostHog Desktop uses Baseten and Modal to process customer data,
              personal data, and PII. They are not currently listed as PostHog
              subprocessors for this feature.
            </Text>
            <Text size="sm" variant="muted">
              Your organization agrees to proceed notwithstanding that status.
              If this feature becomes generally available, PostHog will update
              the DPA and provide notice. This beta may change or be
              discontinued.
            </Text>
            <a
              href="https://posthog.com/subprocessors"
              target="_blank"
              rel="noreferrer"
              className="w-fit text-link text-sm hover:underline"
            >
              View PostHog subprocessors
            </a>
          </div>
        </ConsentDecision>
      )}

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-destructive-foreground text-sm">
          {error}
        </div>
      )}
    </div>
  );
}

interface ConsentDecisionProps {
  title: string;
  summary: ReactNode;
  actionLabel: string;
  adminHelp: string;
  isAdmin: boolean;
  isLoading: boolean;
  isDisabled: boolean;
  onAccept: () => void;
  children: ReactNode;
}

function ConsentDecision({
  title,
  summary,
  actionLabel,
  adminHelp,
  isAdmin,
  isLoading,
  isDisabled,
  onAccept,
  children,
}: ConsentDecisionProps) {
  return (
    <section className="rounded-lg border border-border bg-surface-primary px-4 py-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h2 className="font-semibold text-base text-foreground">{title}</h2>
          <Text className="mt-1" size="sm" variant="muted">
            {summary}
          </Text>
        </div>
        {isAdmin && (
          <Button
            variant="primary"
            size="lg"
            className="h-9 shrink-0 px-3 text-sm"
            loading={isLoading}
            disabled={isDisabled}
            onClick={onAccept}
          >
            {actionLabel}
          </Button>
        )}
      </div>
      {!isAdmin && (
        <Text className="mt-3" size="sm" variant="muted">
          {adminHelp}
        </Text>
      )}
      <Collapsible className="mt-2">
        <CollapsibleTrigger className="px-0 text-muted-foreground">
          Details
        </CollapsibleTrigger>
        <CollapsibleContent className="pt-2 text-sm leading-relaxed">
          {children}
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
