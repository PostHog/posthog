import { ArrowLeft, ArrowRight } from "@phosphor-icons/react";
import { Button, Spinner } from "@posthog/quill";
import { useIsOrgAdmin } from "@posthog/ui/features/auth/useOrgRole";
import { StepActions } from "@posthog/ui/features/onboarding/components/StepActions";
import { useState } from "react";
import { ConsentErrorContent } from "./ConsentErrorContent";
import { ConsentPanel } from "./ConsentPanel";
import { useConsentAnalytics } from "./consentAnalytics";
import { useOrgConsent } from "./useOrgConsent";

interface ConsentStepProps {
  onNext: () => void;
  onBack: () => void;
  onSubmittingChange?: (isSubmitting: boolean) => void;
}

export function ConsentStep({
  onNext,
  onBack,
  onSubmittingChange,
}: ConsentStepProps) {
  const consent = useOrgConsent();
  const { isAdmin } = useIsOrgAdmin();
  const [isSubmitting, setIsSubmitting] = useState(false);
  useConsentAnalytics(consent, isAdmin === true, "onboarding_step");

  return (
    <div className="flex h-full items-center justify-center px-8">
      <div className="flex h-full w-full max-w-[600px] flex-col py-10">
        <div className="flex min-h-0 flex-1 items-center overflow-y-auto">
          {consent.status === "loading" ? (
            <div className="flex w-full justify-center">
              <Spinner />
            </div>
          ) : consent.status === "error" ? (
            <ConsentErrorContent onRetry={consent.retry} />
          ) : (
            <ConsentPanel
              consent={consent}
              isAdmin={isAdmin === true}
              onSubmittingChange={(submitting) => {
                setIsSubmitting(submitting);
                onSubmittingChange?.(submitting);
              }}
            />
          )}
        </div>
        <StepActions>
          <Button
            variant="outline"
            size="lg"
            disabled={isSubmitting}
            onClick={onBack}
          >
            <ArrowLeft size={16} />
            Back
          </Button>
          <Button
            variant="primary"
            size="lg"
            disabled={
              isSubmitting ||
              consent.status !== "resolved" ||
              !consent.satisfied
            }
            onClick={onNext}
          >
            Next
            <ArrowRight size={16} />
          </Button>
        </StepActions>
      </div>
    </div>
  );
}
