import { Avatar, AvatarFallback, AvatarImage } from "@posthog/quill";
import LogosLandscape from "@posthog/ui/primitives/Logo";

/** Up to two letters, so a long org name still fits the avatar. */
function orgInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * The top of Home: whose desktop this is, and a line saying what the rest of
 * the page holds. The org's own mark sits beside PostHog's because the page
 * below is their work, not a product tour.
 */
export function HomeHero({
  orgName,
  logoSrc,
  subhead,
}: {
  orgName: string | null;
  logoSrc?: string;
  subhead: string;
}) {
  return (
    <section className="flex flex-col items-center gap-4 px-6 pt-14 pb-10 text-center">
      <div className="flex items-center gap-4">
        {orgName ? (
          <>
            <Avatar size="lg">
              {logoSrc ? <AvatarImage src={logoSrc} alt={orgName} /> : null}
              <AvatarFallback>{orgInitials(orgName)}</AvatarFallback>
            </Avatar>
            <span aria-hidden className="text-lg text-muted-foreground">
              ×
            </span>
          </>
        ) : null}
        <div className="h-9 [&>svg]:h-9 [&>svg]:w-auto">
          <LogosLandscape code={false} wordmark={false} />
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <h1 className="font-semibold text-2xl">Welcome to PostHog Desktop</h1>
        <p className="text-muted-foreground text-sm">{subhead}</p>
      </div>
    </section>
  );
}
