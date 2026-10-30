import { Text, useAnimation } from "ink";
import type { ReactElement } from "react";

const FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

export function Spinner({ label }: { label?: string }): ReactElement {
  const { frame } = useAnimation({ interval: 80 });
  return (
    <Text color="gray">
      {FRAMES[frame % FRAMES.length]}
      {label ? ` ${label}` : ""}
    </Text>
  );
}
