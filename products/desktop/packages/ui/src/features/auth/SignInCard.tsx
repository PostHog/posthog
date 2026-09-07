import type { DeploymentTarget } from "@posthog/core/auth/schemas";
import { ProductWordmark } from "@posthog/ui/primitives/ProductWordmark";
import { OAuthControls } from "./OAuthControls";

interface SignInCardProps {
  onAuthInitiated?: (region: DeploymentTarget) => void;
  includeDevRegion?: boolean;
}

export function SignInCard({
  onAuthInitiated,
  includeDevRegion,
}: SignInCardProps) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex justify-center">
        <ProductWordmark />
      </div>
      <OAuthControls
        onAuthInitiated={onAuthInitiated}
        includeDevRegion={includeDevRegion}
      />
    </div>
  );
}
