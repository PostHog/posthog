import { Label, Switch } from "@posthog/quill";

export interface OnboardingDebugOverrides {
  selfDrivingOff: boolean;
  autoresearchOff: boolean;
}

interface OnboardingDebugTogglesProps {
  overrides: OnboardingDebugOverrides;
  onChange: (overrides: OnboardingDebugOverrides) => void;
}

const TOGGLES: { key: keyof OnboardingDebugOverrides; label: string }[] = [
  { key: "selfDrivingOff", label: "Self-driving off" },
  { key: "autoresearchOff", label: "Autoresearch off" },
];

/** Development-only switches to preview the landing page without optional features. */
export function OnboardingDebugToggles({
  overrides,
  onChange,
}: OnboardingDebugTogglesProps) {
  return (
    <div className="absolute top-3 right-3 z-10 flex flex-col gap-2 rounded-(--radius-2) border border-border bg-card p-3 shadow-md">
      <span className="font-medium text-muted-foreground text-xs">Debug</span>
      {TOGGLES.map(({ key, label }) => (
        <div key={key} className="flex items-center gap-2">
          <Switch
            id={`onboarding-debug-${key}`}
            size="sm"
            checked={overrides[key]}
            onCheckedChange={(checked: boolean) =>
              onChange({ ...overrides, [key]: checked })
            }
          />
          <Label htmlFor={`onboarding-debug-${key}`} className="text-xs">
            {label}
          </Label>
        </div>
      ))}
    </div>
  );
}
