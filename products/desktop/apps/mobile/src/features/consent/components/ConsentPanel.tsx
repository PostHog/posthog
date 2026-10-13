import { Text } from "@components/text";
import { useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";

type Requirement = "ai" | "beta";

interface ConsentPanelProps {
  organizationName?: string;
  needsAiConsent: boolean;
  needsBetaTerms: boolean;
  isAdmin: boolean;
  onAcceptAi: () => Promise<void>;
  onAcceptBeta: () => Promise<void>;
}

const ERROR_COPY: Record<Requirement, string> = {
  ai: "Couldn't approve AI data processing. Try again, or contact support.",
  beta: "Couldn't save your beta terms acceptance. Try again, or contact support.",
};

export function ConsentPanel({
  organizationName,
  needsAiConsent,
  needsBetaTerms,
  isAdmin,
  onAcceptAi,
  onAcceptBeta,
}: ConsentPanelProps) {
  const [submitting, setSubmitting] = useState<Requirement | null>(null);
  const [error, setError] = useState<string | null>(null);

  const accept = async (kind: Requirement): Promise<void> => {
    if (submitting) return;
    setError(null);
    setSubmitting(kind);
    try {
      await (kind === "ai" ? onAcceptAi() : onAcceptBeta());
    } catch {
      setError(ERROR_COPY[kind]);
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <View className="gap-5">
      <View className="gap-1">
        <Text className="font-semibold text-2xl text-gray-12">
          Before you continue
        </Text>
        <Text className="text-base text-gray-11">
          {organizationName
            ? `Review the required items for ${organizationName}.`
            : "Review the required items for your organization."}
        </Text>
      </View>

      {needsAiConsent && (
        <ConsentCard
          title="PostHog AI needs approval"
          summary={
            organizationName
              ? `${organizationName} hasn't approved AI data processing yet.`
              : "Your organization hasn't approved AI data processing yet."
          }
          detail="PostHog AI features process identifying user data with external AI providers. Your data won't be used to train their models."
          actionLabel="Approve AI data processing"
          adminHelp="Ask an organization admin to approve AI data processing."
          isAdmin={isAdmin}
          isSubmitting={submitting === "ai"}
          isDisabled={submitting !== null}
          onAccept={() => void accept("ai")}
        />
      )}

      {needsBetaTerms && (
        <ConsentCard
          title="PostHog Desktop beta terms"
          summary="Accept the additional data-processing terms for the PostHog Desktop beta."
          detail="PostHog Desktop uses Baseten and Modal to process customer data, personal data, and PII. They aren't listed as PostHog subprocessors for this feature yet. Your organization agrees to proceed. This beta may change or be discontinued."
          actionLabel="Accept beta terms"
          adminHelp="Ask an organization admin to accept the Desktop beta terms."
          isAdmin={isAdmin}
          isSubmitting={submitting === "beta"}
          isDisabled={submitting !== null}
          onAccept={() => void accept("beta")}
          link={{
            label: "View PostHog subprocessors",
            url: "https://posthog.com/subprocessors",
          }}
        />
      )}

      {error && (
        <View className="rounded-lg border border-status-error bg-status-error/10 p-3">
          <Text className="text-sm text-status-error">{error}</Text>
        </View>
      )}
    </View>
  );
}

interface ConsentCardProps {
  title: string;
  summary: string;
  detail: string;
  actionLabel: string;
  adminHelp: string;
  isAdmin: boolean;
  isSubmitting: boolean;
  isDisabled: boolean;
  onAccept: () => void;
  link?: { label: string; url: string };
}

function ConsentCard({
  title,
  summary,
  detail,
  actionLabel,
  adminHelp,
  isAdmin,
  isSubmitting,
  isDisabled,
  onAccept,
  link,
}: ConsentCardProps) {
  const themeColors = useThemeColors();

  return (
    <View className="gap-3 rounded-lg border border-gray-6 bg-gray-2 p-4">
      <View className="gap-1">
        <Text className="font-semibold text-base text-gray-12">{title}</Text>
        <Text className="text-gray-11 text-sm">{summary}</Text>
      </View>
      <Text className="text-gray-11 text-sm leading-5">{detail}</Text>
      {link && (
        <Pressable onPress={() => openExternalUrl(link.url)}>
          <Text className="text-accent-11 text-sm">{link.label}</Text>
        </Pressable>
      )}
      {isAdmin ? (
        <Pressable
          className={`mt-1 items-center rounded-lg py-3 ${
            isDisabled ? "bg-gray-7" : "bg-accent-9 active:opacity-80"
          }`}
          onPress={onAccept}
          disabled={isDisabled}
        >
          {isSubmitting ? (
            <ActivityIndicator color={themeColors.accent.contrast} />
          ) : (
            <Text className="font-semibold text-accent-contrast text-sm">
              {actionLabel}
            </Text>
          )}
        </Pressable>
      ) : (
        <Text className="text-gray-11 text-sm">{adminHelp}</Text>
      )}
    </View>
  );
}
