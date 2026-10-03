import { motion, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";

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
  const shouldReduceMotion = useReducedMotion() === true;

  return (
    <motion.div
      initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay }}
      style={{ zIndex: 1 }}
      className="relative shrink-0"
    >
      <div className="flex items-center justify-end gap-2">
        {children}
        {primaryAction}
      </div>
    </motion.div>
  );
}
