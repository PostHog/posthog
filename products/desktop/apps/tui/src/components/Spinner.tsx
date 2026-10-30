import { Text, useAnimation } from "ink";
import type { ReactElement } from "react";
import { ANIMATION_MS } from "../animation";

const FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

export function Spinner({
  label,
  color = "gray",
}: {
  label?: string;
  // An empty colour draws in the terminal's own text colour.
  color?: string;
}): ReactElement {
  const { frame } = useAnimation({ interval: ANIMATION_MS });
  return (
    <Text color={color}>
      {FRAMES[frame % FRAMES.length]}
      {label ? ` ${label}` : ""}
    </Text>
  );
}
