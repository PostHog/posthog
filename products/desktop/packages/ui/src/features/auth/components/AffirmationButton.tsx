import { Heart } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { useState } from "react";

const AFFIRMATIONS = [
  "You don't need help. You are enough.",
  "You can do it. Try harder.",
  "Have you tried believing in yourself?",
  "The answer was inside you the whole time.",
  "This is not a setback. It is a growth opportunity.",
  "You are exactly where you need to be.",
  "Somewhere out there, someone believes in you.",
];

export function AffirmationButton() {
  const [index, setIndex] = useState<number | null>(null);

  return (
    <div className="flex items-center gap-3">
      <Button
        variant="default"
        size="sm"
        className="text-(--gray-11) opacity-50"
        onClick={() =>
          setIndex((current) =>
            current === null ? 0 : (current + 1) % AFFIRMATIONS.length,
          )
        }
      >
        <Heart size={14} />
        Need support?
      </Button>
      <span aria-live="polite" className="text-(--gray-11) text-xs">
        {index === null ? null : AFFIRMATIONS[index]}
      </span>
    </div>
  );
}
