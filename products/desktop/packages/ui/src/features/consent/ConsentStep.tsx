import { ArrowLeft, ArrowRight } from "@phosphor-icons/react";
import { Button, Spinner } from "@posthog/quill";
import { useIsOrgAdmin } from "@posthog/ui/features/auth/useOrgRole";
import { StepActions } from "@posthog/ui/features/onboarding/components/StepActions";
import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { ConsentErrorContent } from "./ConsentErrorContent";
import { ConsentPanel } from "./ConsentPanel";
import { useConsentAnalytics } from "./consentAnalytics";
import { useOrgConsent } from "./useOrgConsent";

interface ConsentStepProps {
  onNext: () => void;
  onBack?: () => void;
  requirements?: {
    needsAiConsent: boolean;
    needsBetaTerms: boolean;
  };
  onSubmittingChange?: (isSubmitting: boolean) => void;
}

export function ConsentStep({
  onNext,
  onBack,
  requirements,
  onSubmittingChange,
}: ConsentStepProps) {
  const consent = useOrgConsent();
  const { isAdmin } = useIsOrgAdmin();
  const [isSubmitting, setIsSubmitting] = useState(false);
  useConsentAnalytics(consent, isAdmin === true, "onboarding_step");

  return (
    <div className="flex h-full items-center px-8">
      <div className="flex h-full w-full flex-col items-center pt-[24px] pb-[40px]">
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <div className="m-auto w-full max-w-[480px]">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={consent.status}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.16 }}
              >
                {consent.status === "loading" ? (
                  <div className="flex w-full justify-center">
                    <Spinner />
                  </div>
                ) : consent.status === "error" ? (
                  <ConsentErrorContent onRetry={consent.retry} />
                ) : (
                  <ConsentPanel
                    consent={consent}
                    requirements={requirements}
                    isAdmin={isAdmin === true}
                    onSubmittingChange={(submitting) => {
                      setIsSubmitting(submitting);
                      onSubmittingChange?.(submitting);
                    }}
                  />
                )}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
        <StepActions>
          {onBack && (
            <Button
              variant="outline"
              size="lg"
              className="h-10 px-4 text-sm"
              disabled={isSubmitting}
              onClick={onBack}
            >
              <ArrowLeft size={16} />
              Back
            </Button>
          )}
          <Button
            variant="primary"
            size="lg"
            className="h-10 px-4 text-sm"
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
