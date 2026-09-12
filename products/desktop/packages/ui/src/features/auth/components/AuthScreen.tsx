import { SignInCard } from "@posthog/ui/features/auth/SignInCard";
import { FullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import { useAuthStateValue } from "../store";
import { AffirmationButton } from "./AffirmationButton";

interface AuthScreenProps {
  onOpenSupport: () => void;
}

export function AuthScreen({ onOpenSupport }: AuthScreenProps) {
  const sessionEndReason = useAuthStateValue((state) => state.sessionEndReason);
  return (
    <FullScreenLayout
      footerLeft={<AffirmationButton onOpenSupport={onOpenSupport} />}
    >
      <div className="flex h-full items-center justify-center px-12">
        <div className="flex h-full w-full max-w-[480px] flex-col items-center pt-[24px] pb-[40px]">
          <div className="flex min-h-0 w-full flex-1 flex-col items-center justify-center">
            <div className="flex w-full flex-col items-start gap-8">
              <div className="flex w-full flex-col gap-6">
                {sessionEndReason === "impersonation_expired" && (
                  <div className="rounded-(--radius-4) bg-(--amber-a3) p-4 text-(--amber-a11) text-[14px] leading-[20px]">
                    Your impersonated session ended. Impersonate the user again,
                    then sign in to continue.
                  </div>
                )}
                <SignInCard />
              </div>
            </div>
          </div>
        </div>
      </div>
    </FullScreenLayout>
  );
}
