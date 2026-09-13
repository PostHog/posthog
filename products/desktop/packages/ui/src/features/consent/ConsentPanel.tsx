import {
  ArrowClockwise,
  CheckCircle,
  Link as LinkIcon,
} from "@phosphor-icons/react";
import {
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
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { desktopBetaTermsKeys, type OrgConsent } from "./useOrgConsent";

const AI_CONSENT_SETTINGS_URL =
  "https://app.posthog.com/settings/organization-details#organization-ai-consent";
const BETA_TERMS_SETTINGS_URL =
  "https://app.posthog.com/settings/organization-details#organization-desktop-beta-terms";

async function copySettingsLink(
  url: string,
  consentType: "ai" | "desktop_beta_terms",
): Promise<void> {
  try {
    await navigator.clipboard.writeText(url);
    track(ANALYTICS_EVENTS.CONSENT_ADMIN_LINK_COPIED, {
      consent_type: consentType,
      success: true,
    });
    toast.success("Link copied");
  } catch {
    track(ANALYTICS_EVENTS.CONSENT_ADMIN_LINK_COPIED, {
      consent_type: consentType,
      success: false,
    });
    toast.error("Couldn't copy link");
  }
}

interface ConsentPanelProps {
  consent: Extract<OrgConsent, { status: "resolved" }>;
  requirements?: {
    needsAiConsent: boolean;
    needsBetaTerms: boolean;
  };
  isAdmin: boolean;
  onSubmittingChange?: (isSubmitting: boolean) => void;
}

export function ConsentPanel({
  consent,
  requirements,
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
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const organization = currentUser?.organization;
  const showAiConsent = requirements?.needsAiConsent ?? consent.needsAiConsent;
  const showBetaTerms = requirements?.needsBetaTerms ?? consent.needsBetaTerms;

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

  const refresh = async (): Promise<void> => {
    if (refreshing || submitting) return;
    setRefreshing(true);
    setError(null);
    try {
      await consent.retry();
    } catch {
      setError(
        "Could not refresh organization consent. Try again or contact support.",
      );
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="flex w-full max-w-[560px] flex-col gap-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col gap-2">
          <h1 className="font-bold text-2xl text-foreground tracking-[-0.02em]">
            Before you continue
          </h1>
          <Text size="sm" variant="muted">
            {organization?.name
              ? `Review the required items for ${organization.name}.`
              : "Review the required items for your organization."}
          </Text>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          loading={refreshing}
          disabled={submitting !== null}
          data-attr="consent-refresh"
          onClick={() => void refresh()}
        >
          <ArrowClockwise />
          Refresh
        </Button>
      </div>

      {showAiConsent && (
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
          accepted={!consent.needsAiConsent}
          isAdmin={isAdmin}
          isLoading={submitting === "ai"}
          isDisabled={submitting !== null || !organization}
          settingsUrl={AI_CONSENT_SETTINGS_URL}
          consentType="ai"
          copyLinkDataAttr="copy-ai-consent-admin-link"
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

      {showBetaTerms && (
        <ConsentDecision
          title="PostHog Desktop beta terms"
          summary="Accept the additional data-processing terms for the PostHog Desktop beta."
          actionLabel="Accept beta terms"
          adminHelp="Ask an organization admin to accept the Desktop beta terms."
          accepted={!consent.needsBetaTerms}
          isAdmin={isAdmin}
          isLoading={submitting === "beta"}
          isDisabled={submitting !== null || !organization}
          settingsUrl={BETA_TERMS_SETTINGS_URL}
          consentType="desktop_beta_terms"
          copyLinkDataAttr="copy-desktop-beta-terms-admin-link"
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
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-destructive-foreground text-sm"
        >
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
  accepted: boolean;
  isAdmin: boolean;
  isLoading: boolean;
  isDisabled: boolean;
  settingsUrl: string;
  consentType: "ai" | "desktop_beta_terms";
  copyLinkDataAttr: string;
  onAccept: () => void;
  children: ReactNode;
}

function ConsentDecision({
  title,
  summary,
  actionLabel,
  adminHelp,
  accepted,
  isAdmin,
  isLoading,
  isDisabled,
  settingsUrl,
  consentType,
  copyLinkDataAttr,
  onAccept,
  children,
}: ConsentDecisionProps) {
  return (
    <section
      className="rounded-lg border border-border bg-surface-primary px-4 py-4 transition-colors data-[accepted=true]:border-success-foreground/25"
      data-accepted={accepted}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h2 className="font-semibold text-base text-foreground">{title}</h2>
          <Text className="mt-1" size="sm" variant="muted">
            {summary}
          </Text>
        </div>
        {accepted ? (
          <Button
            variant="outline"
            size="lg"
            className="h-9 shrink-0 px-3 text-sm text-success-foreground"
            disabled
          >
            <CheckCircle size={16} />
            Accepted
          </Button>
        ) : isAdmin ? (
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
        ) : null}
      </div>
      {!accepted && !isAdmin && (
        <div className="mt-3 flex flex-col items-start gap-2">
          <Text size="sm" variant="muted">
            {adminHelp}
          </Text>
          <Button
            variant="outline"
            size="sm"
            data-attr={copyLinkDataAttr}
            onClick={() => void copySettingsLink(settingsUrl, consentType)}
          >
            <LinkIcon />
            Copy link
          </Button>
        </div>
      )}
      <Collapsible className="mt-3 border-border border-t pt-2">
        <CollapsibleTrigger className="-ml-2 h-7 rounded-md px-2 text-muted-foreground hover:bg-fill-hover hover:text-foreground">
          Details
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-1 ml-1 border-border border-l py-1 pl-3 text-sm leading-relaxed">
          {children}
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
