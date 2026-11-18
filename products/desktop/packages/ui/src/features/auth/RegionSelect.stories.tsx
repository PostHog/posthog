import type { CloudRegion } from "@posthog/shared";
import { CustomCloudFields } from "@posthog/ui/features/auth/CustomCloudFields";
import { RegionSelect } from "@posthog/ui/features/auth/RegionSelect";
import type { CustomCloudDraft } from "@posthog/ui/features/auth/useCustomCloud";
import { ProductWordmark } from "@posthog/ui/primitives/ProductWordmark";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

const meta: Meta<typeof RegionSelect> = {
  title: "Auth/RegionSelect",
  component: RegionSelect,
};

export default meta;

/** Mirrors SignInCard's layout without the OAuth hook, so the whole block is visible. */
function SignInCardPreview({
  includeDevRegion,
  includeCustomRegion = false,
  initialRegion = "us",
  customCloudDraft,
}: {
  includeDevRegion: boolean;
  includeCustomRegion?: boolean;
  initialRegion?: CloudRegion;
  customCloudDraft?: CustomCloudDraft;
}) {
  const [region, setRegion] = useState<CloudRegion>(initialRegion);
  const [draft, setDraft] = useState<CustomCloudDraft>(
    customCloudDraft ?? {
      url: "",
      oauthClientId: "",
      gatewayUrl: "",
    },
  );
  return (
    <div className="w-[420px] p-8">
      <div className="flex flex-col gap-6">
        <div className="flex justify-center">
          <ProductWordmark />
        </div>
        <div className="flex w-full flex-col gap-3">
          <button
            type="button"
            className="flex h-[44px] w-full cursor-pointer items-center justify-center gap-[8px] rounded-[6px] font-medium text-[15px]"
            style={{
              border: "1.5px solid var(--accent-8)",
              backgroundColor: "var(--accent-9)",
              color: "var(--accent-contrast)",
              boxShadow: "0 3px 0 -1px var(--accent-8)",
            }}
          >
            Sign in with PostHog
          </button>
          <RegionSelect
            region={region}
            onRegionChange={setRegion}
            includeDevRegion={includeDevRegion}
            includeCustomRegion={includeCustomRegion}
          />
          {region === "custom" && (
            <CustomCloudFields
              draft={draft}
              onChange={(patch) =>
                setDraft((current) => ({ ...current, ...patch }))
              }
              onBlur={() => undefined}
              error={null}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export const SignInBlock: StoryObj = {
  render: () => <SignInCardPreview includeDevRegion={false} />,
};

export const WithDevelopmentRegions: StoryObj = {
  render: () => <SignInCardPreview includeDevRegion={true} />,
};

export const CustomCloudEmpty: StoryObj = {
  render: () => (
    <SignInCardPreview
      includeDevRegion={true}
      includeCustomRegion={true}
      initialRegion="custom"
    />
  ),
};

export const CustomCloudFilled: StoryObj = {
  render: () => (
    <SignInCardPreview
      includeDevRegion={true}
      includeCustomRegion={true}
      initialRegion="custom"
      customCloudDraft={{
        url: "https://posthog.example.com",
        oauthClientId: "3Fk9QwErTyUiOpAsDfGhJkLzXcVbNm12",
        gatewayUrl: "https://gateway.example.com",
      }}
    />
  ),
};
