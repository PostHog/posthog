import { Check } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import type { ThemePreference } from "@posthog/ui/shell/themeStore";
import type { CSSProperties } from "react";

interface ThemePalette {
  canvas: string;
  sidebar: string;
  bar: string;
  accent: string;
}

// Fixed hexes rather than theme tokens: each thumbnail must show its own
// theme regardless of the theme applied to the app.
const LIGHT_PALETTE: ThemePalette = {
  canvas: "#fdfdfc",
  sidebar: "#f1f0ee",
  bar: "#d9d7d3",
  accent: "#f54e00",
};

const DARK_PALETTE: ThemePalette = {
  canvas: "#191918",
  sidebar: "#232322",
  bar: "#403f3d",
  accent: "#f54e00",
};

const THEME_OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

function MiniWindow({
  palette,
  className,
  style,
}: {
  palette: ThemePalette;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      aria-hidden
      className={cn("flex", className)}
      style={{ backgroundColor: palette.canvas, ...style }}
    >
      <div
        className="flex w-1/4 flex-col gap-1 p-1.5"
        style={{ backgroundColor: palette.sidebar }}
      >
        <div
          className="h-1 w-full rounded-full"
          style={{ backgroundColor: palette.bar }}
        />
        <div
          className="h-1 w-2/3 rounded-full"
          style={{ backgroundColor: palette.bar }}
        />
      </div>
      <div className="flex flex-1 flex-col gap-1.5 p-2">
        <div className="flex items-center gap-1">
          <div
            className="size-1.5 shrink-0 rounded-full"
            style={{ backgroundColor: palette.accent }}
          />
          <div
            className="h-1 w-1/2 rounded-full"
            style={{ backgroundColor: palette.bar }}
          />
        </div>
        <div
          className="h-1 w-full rounded-full"
          style={{ backgroundColor: palette.bar }}
        />
        <div
          className="h-1 w-3/4 rounded-full"
          style={{ backgroundColor: palette.bar }}
        />
      </div>
    </div>
  );
}

function ThemeThumbnail({ theme }: { theme: ThemePreference }) {
  if (theme === "system") {
    return (
      <div className="relative h-16 w-full">
        <MiniWindow palette={LIGHT_PALETTE} className="absolute inset-0" />
        <MiniWindow
          palette={DARK_PALETTE}
          className="absolute inset-0"
          style={{ clipPath: "polygon(100% 0, 100% 100%, 0 100%)" }}
        />
      </div>
    );
  }
  return (
    <MiniWindow
      palette={theme === "light" ? LIGHT_PALETTE : DARK_PALETTE}
      className="h-16 w-full"
    />
  );
}

interface ThemePickerProps {
  value: ThemePreference;
  onChange: (theme: ThemePreference) => void;
}

/**
 * Theme choice as three mini window previews instead of a dropdown, so the
 * options show what they do.
 */
export function ThemePicker({ value, onChange }: ThemePickerProps) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {THEME_OPTIONS.map((option) => {
        const selected = option.value === value;
        return (
          <label
            key={option.value}
            className={cn(
              "flex cursor-pointer flex-col overflow-hidden rounded-(--radius-3) border bg-(--color-panel-solid) transition-colors has-[:focus-visible]:ring-(--accent-8) has-[:focus-visible]:ring-2",
              selected
                ? "border-(--accent-9)"
                : "border-(--gray-5) hover:border-(--gray-8)",
            )}
          >
            <input
              type="radio"
              name="theme-preference"
              value={option.value}
              checked={selected}
              onChange={() => onChange(option.value)}
              className="sr-only"
              aria-label={`${option.label} theme`}
            />
            <ThemeThumbnail theme={option.value} />
            <div className="flex w-full items-center justify-between border-(--gray-4) border-t px-2.5 py-1.5">
              <span className="text-[12px] text-gray-12">{option.label}</span>
              <span
                className={cn(
                  "flex size-3.5 items-center justify-center rounded-full bg-(--primary) text-(--primary-foreground) transition-opacity",
                  selected ? "opacity-100" : "opacity-0",
                )}
              >
                <Check size={9} weight="bold" />
              </span>
            </div>
          </label>
        );
      })}
    </div>
  );
}
