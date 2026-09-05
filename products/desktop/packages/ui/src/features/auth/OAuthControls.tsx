import type { DeploymentTarget } from "@posthog/core/auth/schemas";
import { useService } from "@posthog/di/react";
import {
  PREVIEW_DEPLOYMENT,
  type PreviewDeploymentInfo,
} from "@posthog/platform/preview-deployment";
import { Callout, Spinner } from "@radix-ui/themes";
import { RegionSelect } from "./RegionSelect";
import { useOAuthFlow } from "./useOAuthFlow";

interface OAuthControlsProps {
  onAuthInitiated?: (region: DeploymentTarget) => void;
  /** Defaults to the dev build, where development targets are available. */
  includeDevRegion?: boolean;
}

export function OAuthControls({
  onAuthInitiated,
  includeDevRegion = import.meta.env.DEV,
}: OAuthControlsProps = {}) {
  const preview = useService<PreviewDeploymentInfo | null>(PREVIEW_DEPLOYMENT);
  const {
    region,
    handleAuth,
    handleRegionChange,
    handleCancel,
    isPending,
    errorMessage,
  } = useOAuthFlow();

  const handleClick = () => {
    if (isPending) {
      void handleCancel();
      return;
    }
    onAuthInitiated?.(region);
    handleAuth();
  };

  return (
    <div className="flex w-full flex-col gap-3">
      {errorMessage && (
        <Callout.Root color="red" size="1">
          <Callout.Text>{errorMessage}</Callout.Text>
        </Callout.Root>
      )}

      {isPending && (
        <Callout.Root color="blue" size="1">
          <Callout.Text>Waiting for authorization...</Callout.Text>
        </Callout.Root>
      )}

      <button
        type="button"
        onClick={handleClick}
        disabled={false}
        className="flex h-[44px] w-full cursor-pointer items-center justify-center gap-[8px] rounded-[6px] font-medium text-[15px]"
        style={{
          border: isPending
            ? "1.5px solid var(--gray-6)"
            : "1.5px solid var(--accent-8)",
          backgroundColor: isPending ? "var(--gray-3)" : "var(--accent-9)",
          color: isPending ? "var(--gray-11)" : "var(--accent-contrast)",
          boxShadow: isPending ? "none" : "0 3px 0 -1px var(--accent-8)",
          transition: "opacity 150ms ease, box-shadow 100ms ease",
        }}
      >
        {isPending && <Spinner size="1" />}
        {isPending ? "Cancel" : "Sign in with PostHog"}
      </button>

      {preview ? (
        // A preview build signs in to exactly one deployment: the isolated
        // backend this installer was built for. No region picker, so nobody
        // can point this app at production projects.
        <div className="flex flex-col items-center gap-1">
          <span className="text-(--gray-11) text-xs">
            Preview deployment: {preview.label}
          </span>
          <span className="text-(--gray-10) text-xs">
            Connects only to this pull request's backend.
          </span>
        </div>
      ) : (
        <RegionSelect
          // In the non-preview branch the region state can only hold an
          // ordinary region: `useOAuthFlow` seeds "preview" only when a
          // preview deployment is bound, and the picker is the only writer.
          region={region === "preview" ? "us" : region}
          onRegionChange={handleRegionChange}
          disabled={isPending}
          includeDevRegion={includeDevRegion}
        />
      )}
    </div>
  );
}
