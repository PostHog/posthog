import { Heart, Lifebuoy } from "@phosphor-icons/react";
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

function pickAffirmation(): string {
  return AFFIRMATIONS[Math.floor(Math.random() * AFFIRMATIONS.length)];
}

interface AffirmationButtonProps {
  onOpenSupport: () => void;
}

export function AffirmationButton({ onOpenSupport }: AffirmationButtonProps) {
  const [affirmation, setAffirmation] = useState<string | null>(null);

  return (
    <div className="flex items-center gap-3">
      <Button
        variant="default"
        size="sm"
        className="text-(--gray-11) opacity-50"
        onClick={() => {
          if (affirmation === null) {
            setAffirmation(pickAffirmation());
          } else {
            onOpenSupport();
          }
        }}
      >
        {affirmation === null ? <Heart size={14} /> : <Lifebuoy size={14} />}
        {affirmation === null ? "Need support?" : "Get support"}
      </Button>
      {affirmation !== null && (
        <span aria-live="polite" className="text-(--gray-11) text-xs">
          {affirmation}
        </span>
      )}
    </div>
  );
}
