import { Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

/**
 * A labelled form control: a consistent label, an optional below-field hint,
 * and a subtle marker for required fields. Shared across the loop form and its
 * sub-editors so every field reads the same.
 */
export function Field({
  label,
  hint,
  required,
  className,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Flex direction="column" gap="2" className={className}>
      <Text as="label" className="font-medium text-[13px] text-gray-12">
        {label}
        {required ? <span className="ml-0.5 text-(--accent-9)">*</span> : null}
      </Text>
      {children}
      {hint ? (
        <Text className="text-[12px] text-gray-10 leading-snug">{hint}</Text>
      ) : null}
    </Flex>
  );
}
