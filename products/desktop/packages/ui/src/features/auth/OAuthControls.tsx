import type { CloudRegion } from "@posthog/shared";
import { Callout, Spinner } from "@radix-ui/themes";
import { RegionSelect } from "./RegionSelect";
import { useOAuthFlow } from "./useOAuthFlow";

interface OAuthControlsProps {
  onAuthInitiated?: (region: CloudRegion) => void;
  /** Defaults to the dev build, which is the only place a local instance is worth offering. */
  includeDevRegion?: boolean;
}

export function OAuthControls({
  onAuthInitiated,
  includeDevRegion = import.meta.env.DEV,
}: OAuthControlsProps = {}) {
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

      <RegionSelect
        region={region}
        onRegionChange={handleRegionChange}
        disabled={isPending}
        includeDevRegion={includeDevRegion}
      />
    </div>
  );
}
