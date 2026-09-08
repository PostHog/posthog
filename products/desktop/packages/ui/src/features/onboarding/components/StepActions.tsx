import { ArrowRight } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { motion, useReducedMotion } from "framer-motion";
import { createContext, type ReactNode, useContext } from "react";

const SkipSetupContext = createContext<(() => void) | undefined>(undefined);

export function SkipSetupProvider({
  children,
  onSkipSetup,
}: {
  children: ReactNode;
  onSkipSetup?: () => void;
}) {
  return (
    <SkipSetupContext.Provider value={onSkipSetup}>
      {children}
    </SkipSetupContext.Provider>
  );
}

interface StepActionsProps {
  children?: ReactNode;
  primaryAction: ReactNode;
  delay?: number;
}

export function StepActions({
  children,
  primaryAction,
  delay = 0.15,
}: StepActionsProps) {
  const onSkipSetup = useContext(SkipSetupContext);
  const shouldReduceMotion = useReducedMotion() === true;

  return (
    <motion.div
      initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay }}
      style={{ zIndex: 1 }}
      className="relative shrink-0 pt-[16px]"
    >
      <div className="flex items-center gap-2">
        {children}
        {onSkipSetup && (
          <Button
            size="sm"
            variant="link-muted"
            className="min-h-11"
            onClick={onSkipSetup}
          >
            Skip setup
            <ArrowRight size={14} weight="bold" />
          </Button>
        )}
        {primaryAction}
      </div>
    </motion.div>
  );
}
