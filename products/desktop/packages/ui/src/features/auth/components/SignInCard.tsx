import type { CloudRegion } from "@posthog/shared";
import { SignInCard as BaseSignInCard } from "../SignInCard";

interface SignInCardProps {
  hogSrc: string;
  hogMessage: string;
  subtitle: string;
  onAuthInitiated?: (region: CloudRegion) => void;
}

export function SignInCard(props: SignInCardProps) {
  return <BaseSignInCard {...props} includeDevRegion={import.meta.env.DEV} />;
}
