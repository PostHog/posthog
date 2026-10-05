import { Text, useAnimation } from "ink";
import type { ReactElement } from "react";

const FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

export function Spinner({
  label,
  color = "gray",
}: {
  label?: string;
  color?: string;
}): ReactElement {
  const { frame } = useAnimation({ interval: 80 });
  return (
    <Text color={color}>
      {FRAMES[frame % FRAMES.length]}
      {label ? ` ${label}` : ""}
    </Text>
  );
}
