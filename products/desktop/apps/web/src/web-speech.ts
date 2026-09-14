import type {
  SpeechSettingsProvider,
  UserNameProvider,
} from "@posthog/core/speech/identifiers";
import type { ISpeech } from "@posthog/platform/speech";
import { authKeys } from "@posthog/ui/features/auth/useCurrentUser";
import type { ISpeechNotifySettings } from "@posthog/ui/features/notifications/identifiers";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import type { ImperativeQueryClient } from "@posthog/ui/shell/queryClient";
import {
  isSpeechSupported,
  speakSystemVoice,
  stopSpeech,
} from "@posthog/ui/utils/speech";

// System voice only: ElevenLabs synthesis needs the key in a host secure store,
// which the browser has no equivalent of. voiceId is therefore ignored.
export const webSpeech: ISpeech = {
  isSupported: () => isSpeechSupported(),
  speak: (text) => speakSystemVoice(text),
  stop: () => stopSpeech(),
};

export const webSpeechSettings: SpeechSettingsProvider = {
  get: () => ({ enabled: useSettingsStore.getState().spokenNotifications }),
};

export const webSpeechNotifySettings: ISpeechNotifySettings = {
  get: () => {
    const s = useSettingsStore.getState();
    return {
      enabled: s.spokenNotifications,
      needsInput: s.spokenNotifyNeedsInput,
      completion: s.spokenNotifyCompletion,
      progress: s.spokenNotifyProgress,
      focusMode: s.spokenFocusMode,
    };
  },
};

export function createWebSpeechUserName(
  queryClient: ImperativeQueryClient,
): UserNameProvider {
  return {
    getFirstName: () => {
      for (const [, data] of queryClient.getQueriesData({
        queryKey: authKeys.currentUsers(),
      })) {
        const first = (
          data as { first_name?: string | null } | undefined
        )?.first_name?.trim();
        if (first) return first;
      }
      return undefined;
    },
  };
}
