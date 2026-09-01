import {
  type HERO_HEDGEHOGS,
  type AnnouncementHero as HeroConfig,
  hoggiePngUrl,
} from "@posthog/shared/announcements";
import {
  builderHog,
  explorerHog,
  happyHog,
  loopHog,
} from "@posthog/ui/assets/hedgehogs";
import { useState } from "react";

type HedgehogName = (typeof HERO_HEDGEHOGS)[number];

const HEDGEHOG_SRC: Record<HedgehogName, string> = {
  builder: builderHog,
  explorer: explorerHog,
  happy: happyHog,
  loop: loopHog,
};

const DEFAULT_COLOR = "#2f80fa";

function bundledSrc(slug: string): string | undefined {
  return (HEDGEHOG_SRC as Record<string, string | undefined>)[slug];
}

function GeometricPattern() {
  return (
    <svg
      className="absolute inset-0 h-full w-full text-white"
      viewBox="0 0 232 96"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <circle cx="26" cy="22" r="11" fill="currentColor" opacity="0.25" />
      <circle
        cx="204"
        cy="66"
        r="17"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        opacity="0.3"
      />
      <rect
        x="176"
        y="10"
        width="15"
        height="15"
        rx="2"
        transform="rotate(18 183 17)"
        fill="currentColor"
        opacity="0.2"
      />
      <polygon points="64,10 75,30 53,30" fill="currentColor" opacity="0.3" />
      <path
        d="M8 62 l7 -8 7 8 7 -8 7 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.35"
      />
      <circle cx="118" cy="14" r="4" fill="currentColor" opacity="0.35" />
      <path
        d="M148 78 h12 M154 72 v12"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        opacity="0.3"
      />
      <circle
        cx="52"
        cy="78"
        r="6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        opacity="0.25"
      />
      <rect
        x="96"
        y="70"
        width="10"
        height="10"
        transform="rotate(-12 101 75)"
        fill="currentColor"
        opacity="0.18"
      />
      <polygon
        points="206,18 214,32 198,32"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinejoin="round"
        opacity="0.3"
      />
    </svg>
  );
}

/**
 * Any hoggie by slug: bundled names render from local assets, everything else
 * streams from the pinned PostHog/brand CDN copy and falls back to the
 * kind-default hedgehog when unreachable (offline, unknown slug).
 */
function HoggieImage({
  slug,
  fallback,
}: {
  slug: string;
  fallback: HedgehogName;
}) {
  const [failed, setFailed] = useState(false);
  const local = bundledSrc(slug);
  const src = local ?? (failed ? HEDGEHOG_SRC[fallback] : hoggiePngUrl(slug));
  return (
    <img
      src={src}
      alt=""
      className="relative h-28 w-auto object-contain"
      onError={() => setFailed(true)}
    />
  );
}

/** The colored band with pattern and hoggie — also the landing spot when a
 * remote hero image fails to load. */
function HedgehogBand({
  hedgehog,
  fallbackHedgehog,
  color,
}: {
  hedgehog: string;
  fallbackHedgehog: HedgehogName;
  color: string;
}) {
  return (
    <div
      className="relative flex h-40 items-center justify-center"
      style={{ backgroundColor: color }}
    >
      <GeometricPattern />
      <HoggieImage key={hedgehog} slug={hedgehog} fallback={fallbackHedgehog} />
      <div className="absolute inset-x-0 bottom-0 h-10 bg-gradient-to-b from-transparent to-(--background)" />
    </div>
  );
}

/**
 * Remote hero image with the same graceful degradation as remote hoggies: an
 * expired URL or offline session falls back to the default hedgehog band
 * instead of a broken-image glyph. Keyed on the URL by the caller so the
 * failure state resets when the payload changes.
 */
function ImageHero({
  url,
  fallbackHedgehog,
  fallbackColor,
}: {
  url: string;
  fallbackHedgehog: HedgehogName;
  fallbackColor: string;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <HedgehogBand
        hedgehog={fallbackHedgehog}
        fallbackHedgehog={fallbackHedgehog}
        color={fallbackColor}
      />
    );
  }
  return (
    <div className="relative h-40 overflow-hidden">
      <img
        src={url}
        alt=""
        referrerPolicy="no-referrer"
        className="h-full w-full object-cover"
        onError={() => setFailed(true)}
      />
      <div className="absolute inset-x-0 bottom-0 h-10 bg-gradient-to-b from-transparent to-(--background)" />
    </div>
  );
}

/**
 * Modal hero band: a colored band with a hedgehog by default, a remote image
 * when the payload provides one, nothing when the payload opts out.
 */
export function AnnouncementHero({
  hero,
  defaultHedgehog,
  defaultColor = DEFAULT_COLOR,
}: {
  hero: HeroConfig | undefined;
  defaultHedgehog: HedgehogName;
  defaultColor?: string;
}) {
  if (hero && "none" in hero) return null;

  if (hero && "imageUrl" in hero) {
    return (
      <ImageHero
        key={hero.imageUrl}
        url={hero.imageUrl}
        fallbackHedgehog={defaultHedgehog}
        fallbackColor={defaultColor}
      />
    );
  }

  const hedgehog = hero && "hedgehog" in hero ? hero.hedgehog : defaultHedgehog;
  const color =
    (hero && "hedgehog" in hero ? hero.color : undefined) ?? defaultColor;
  return (
    <HedgehogBand
      hedgehog={hedgehog}
      fallbackHedgehog={defaultHedgehog}
      color={color}
    />
  );
}
