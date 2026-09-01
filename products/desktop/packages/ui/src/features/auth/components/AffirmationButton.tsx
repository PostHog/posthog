import { Heart, Lifebuoy } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { useState } from "react";

const AFFIRMATION = "You don't need help. You are enough.";

interface AffirmationButtonProps {
  onOpenSupport: () => void;
}

export function AffirmationButton({ onOpenSupport }: AffirmationButtonProps) {
  const [hasShownAffirmation, setHasShownAffirmation] = useState(false);

  return (
    <div className="flex items-center gap-3">
      <Button
        variant="default"
        size="sm"
        className="text-(--gray-11) opacity-50"
        onClick={() => {
          if (hasShownAffirmation) {
            onOpenSupport();
          } else {
            setHasShownAffirmation(true);
          }
        }}
      >
        {hasShownAffirmation ? <Lifebuoy size={14} /> : <Heart size={14} />}
        {hasShownAffirmation ? "Get support" : "Need support?"}
      </Button>
      {hasShownAffirmation && (
        <span aria-live="polite" className="text-(--gray-11) text-xs">
          {AFFIRMATION}
        </span>
      )}
    </div>
  );
}
