import { GithubLogoIcon, HeartIcon } from "@phosphor-icons/react";
import Logo from "@posthog/ui/primitives/Logo";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { domAnimation, LazyMotion, m, useReducedMotion } from "framer-motion";

interface GithubConnectionIconProps {
  connected: boolean;
  loading?: boolean;
}

export function GithubConnectionIcon({
  connected,
  loading = false,
}: GithubConnectionIconProps) {
  const shouldReduceMotion = useReducedMotion() === true;
  const movementTransition = {
    duration: shouldReduceMotion ? 0 : 0.55,
    delay: shouldReduceMotion ? 0 : 0.12,
    ease: [0.645, 0.045, 0.355, 1] as const,
  };
  const enterTransition = {
    duration: shouldReduceMotion ? 0 : 0.28,
    delay: shouldReduceMotion ? 0 : 0.8,
    ease: [0.215, 0.61, 0.355, 1] as const,
  };
  const tileClassName =
    "absolute top-1/2 left-1/2 flex size-8 items-center justify-center rounded-md border border-border bg-muted";

  return (
    <LazyMotion features={domAnimation}>
      {connected ? (
        <div
          key="connected"
          className="relative h-8 w-28"
          aria-label="PostHog connected to GitHub"
          role="img"
        >
          <m.span
            aria-hidden="true"
            className={tileClassName}
            initial={
              shouldReduceMotion
                ? false
                : {
                    opacity: 0,
                    transform: "translate(-50%, -50%) scale(0.92)",
                  }
            }
            animate={{
              opacity: 1,
              transform: "translate(-52px, -50%) scale(1)",
            }}
            transition={movementTransition}
          >
            <span className="[&>svg]:h-3.5 [&>svg]:w-auto">
              <Logo wordmark={false} />
            </span>
          </m.span>

          <m.span
            aria-hidden="true"
            className="absolute top-1/2 left-1/2 flex items-center justify-center text-destructive-foreground"
            initial={
              shouldReduceMotion
                ? false
                : {
                    opacity: 0,
                    transform: "translate(-50%, -50%) scale(0.6)",
                  }
            }
            animate={{
              opacity: 1,
              transform: "translate(-50%, -50%) scale(1)",
            }}
            transition={enterTransition}
          >
            <HeartIcon size={14} weight="fill" />
          </m.span>

          <m.span
            aria-hidden="true"
            className={tileClassName}
            initial={
              shouldReduceMotion
                ? false
                : {
                    opacity: 0,
                    transform: "translate(-50%, -50%) scale(0.92)",
                  }
            }
            animate={{
              opacity: 1,
              transform: "translate(20px, -50%) scale(1)",
            }}
            transition={movementTransition}
          >
            <GithubLogoIcon size={17} weight="fill" />
          </m.span>
        </div>
      ) : (
        <div className="relative h-8 w-28" aria-label="GitHub" role="img">
          <m.span
            aria-hidden="true"
            className={tileClassName}
            initial={false}
            animate={{
              opacity: loading ? 0 : 1,
              transform: "translate(-50%, -50%) scale(1)",
            }}
            transition={{
              duration: shouldReduceMotion ? 0 : 0.15,
              ease: [0.215, 0.61, 0.355, 1],
            }}
          >
            <GithubLogoIcon size={17} weight="fill" />
          </m.span>

          <m.span
            aria-hidden="true"
            className="absolute inset-0 flex items-center justify-center"
            initial={false}
            animate={{
              opacity: loading ? 1 : 0,
              transform: loading ? "scale(1)" : "scale(0.92)",
            }}
            transition={{
              duration: shouldReduceMotion ? 0 : 0.15,
              ease: [0.215, 0.61, 0.355, 1],
            }}
          >
            <span className="flex size-8 items-center justify-center rounded-md bg-muted">
              <Spinner />
            </span>
          </m.span>
        </div>
      )}
    </LazyMotion>
  );
}
