import { ArrowsOut } from "@phosphor-icons/react";
import { Flex, Text } from "@radix-ui/themes";
import { motion } from "framer-motion";
import { type KeyboardEvent, type ReactNode, useEffect, useRef } from "react";
import "./FeatureBentoCard.css";

interface FeatureBentoCardProps {
  icon: ReactNode;
  title: string;
  description: string;
  /** Highlights the card (the featured card when nothing is hovered). */
  active?: boolean;
  index?: number;
  /** Optional looping demo video shown in the placeholder area. */
  videoSrc?: string;
  /** Still frame shown until the video plays. Should match `videoStartTime`. */
  posterSrc?: string;
  /** Timestamp (seconds) the still is taken from; playback starts and loops here. */
  videoStartTime?: number;
  /** When true, this card's video plays. Only one card plays at a time. */
  shouldPlay?: boolean;
  /** Click handler that promotes this card into the large slot. */
  onSelect?: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function FeatureBentoCard({
  icon,
  title,
  description,
  active = false,
  index = 0,
  videoSrc,
  posterSrc,
  videoStartTime = 0,
  shouldPlay = false,
  onSelect,
  onMouseEnter,
  onMouseLeave,
}: FeatureBentoCardProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const selectable = Boolean(onSelect);

  // Park the video on the still frame so it matches the poster, even after the
  // browser has decoded it (poster only shows before the first play).
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !videoSrc) return;

    const seekToStart = () => {
      try {
        video.currentTime = videoStartTime;
      } catch {
        // Seeking before metadata is ready is a no-op; the listener retries.
      }
    };

    if (video.readyState >= 1) {
      seekToStart();
      return;
    }
    video.addEventListener("loadedmetadata", seekToStart, { once: true });
    return () => video.removeEventListener("loadedmetadata", seekToStart);
  }, [videoSrc, videoStartTime]);

  // Play only when told to; otherwise rest on the still frame.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !videoSrc) return;

    if (shouldPlay && !prefersReducedMotion()) {
      void video.play().catch(() => {
        // Ignore: play() can reject if the element isn't ready yet.
      });
    } else {
      video.pause();
      try {
        video.currentTime = videoStartTime;
      } catch {
        // Ignore: resetting before metadata is ready is a no-op.
      }
    }
  }, [shouldPlay, videoSrc, videoStartTime]);

  // Loop back to the still frame rather than the very start of the clip.
  const handleVideoEnded = () => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = videoStartTime;
    if (shouldPlay && !prefersReducedMotion()) {
      void video.play().catch(() => {});
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!selectable) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect?.();
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.08 }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onClick={selectable ? onSelect : undefined}
      onKeyDown={selectable ? handleKeyDown : undefined}
      role={selectable ? "button" : undefined}
      tabIndex={selectable ? 0 : undefined}
      aria-label={selectable ? `Show ${title}` : undefined}
      className={`feature-bento-card h-full w-full ${active ? "feature-bento-card--active" : ""} ${selectable ? "feature-bento-card--selectable" : ""}`}
    >
      <div
        className={`feature-bento-card__placeholder ${videoSrc ? "feature-bento-card__placeholder--media" : ""}`}
      >
        {videoSrc ? (
          <video
            ref={videoRef}
            className="feature-bento-card__video"
            src={videoSrc}
            poster={posterSrc}
            muted
            playsInline
            preload="metadata"
            onEnded={handleVideoEnded}
          />
        ) : (
          <>
            <div
              className="feature-bento-card__placeholder-grid"
              aria-hidden="true"
            />
            <div
              className="feature-bento-card__placeholder-glow"
              aria-hidden="true"
            />
            <Flex
              align="center"
              justify="center"
              className="relative z-10 text-(--gray-9)"
            >
              <div className="feature-bento-card__icon">{icon}</div>
            </Flex>
          </>
        )}
        {selectable && (
          <div className="feature-bento-card__expand-hint" aria-hidden="true">
            <ArrowsOut size={13} weight="bold" />
          </div>
        )}
      </div>
      <Flex
        direction="column"
        gap="1"
        className="feature-bento-card__content shrink-0 px-1 pt-3 pb-1"
      >
        <Text className="font-medium text-(--gray-12) text-sm leading-snug">
          {title}
        </Text>
        <Text className="text-(--gray-11) text-[12px] leading-snug">
          {description}
        </Text>
      </Flex>
    </motion.div>
  );
}
