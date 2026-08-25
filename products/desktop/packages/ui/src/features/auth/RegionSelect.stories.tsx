import type { CloudRegion } from "@posthog/shared";
import { RegionSelect } from "@posthog/ui/features/auth/RegionSelect";
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
}: {
  includeDevRegion: boolean;
}) {
  const [region, setRegion] = useState<CloudRegion>("us");
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
          />
        </div>
      </div>
    </div>
  );
}

export const SignInBlock: StoryObj = {
  render: () => <SignInCardPreview includeDevRegion={false} />,
};

export const WithDevRegion: StoryObj = {
  render: () => <SignInCardPreview includeDevRegion={true} />,
};
