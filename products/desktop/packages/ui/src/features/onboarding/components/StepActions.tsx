import { Flex } from "@radix-ui/themes";
import { motion } from "framer-motion";
import type { ReactNode } from "react";

interface StepActionsProps {
  children: ReactNode;
  delay?: number;
}

export function StepActions({ children, delay = 0.15 }: StepActionsProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay }}
      style={{ zIndex: 1 }}
      className="relative shrink-0 pt-[16px]"
    >
      <Flex gap="4" align="center">
        {children}
      </Flex>
    </motion.div>
  );
}
