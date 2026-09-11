import { getPiSubscriptionCredential } from "@posthog/agent/pi/subscription-login-client";
import type { PiSubscriptionCredentialStore } from "@posthog/core/cloud-task/identifiers";
import type {
  PiSubscriptionCredential,
  PiSubscriptionProvider,
} from "@posthog/shared";

export class ElectronPiSubscriptionCredentialStore
  implements PiSubscriptionCredentialStore
{
  get(
    provider: PiSubscriptionProvider,
  ): Promise<PiSubscriptionCredential | null> {
    return getPiSubscriptionCredential(provider);
  }
}
