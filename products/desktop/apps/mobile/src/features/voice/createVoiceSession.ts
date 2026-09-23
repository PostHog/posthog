import { TypedContainer } from "@inversifyjs/strongly-typed";
import {
  CONVERSATION_VOICE_SESSION,
  ConversationVoiceSession,
  VOICE_CONVERSATION,
  type VoiceConversation,
} from "@posthog/core/voice/conversationVoiceSession";
import {
  LIVE_VOICE_TRANSPORT,
  type LiveVoiceTransport,
} from "@posthog/platform/speech";
import { NativeVoiceTransport } from "./nativeVoiceTransport";

interface VoiceBindings {
  [CONVERSATION_VOICE_SESSION]: ConversationVoiceSession;
  [LIVE_VOICE_TRANSPORT]: LiveVoiceTransport;
  [VOICE_CONVERSATION]: VoiceConversation;
}

export function createVoiceSession(
  conversation: VoiceConversation,
): ConversationVoiceSession {
  const container = new TypedContainer<VoiceBindings>();
  container
    .bind(LIVE_VOICE_TRANSPORT)
    .toConstantValue(new NativeVoiceTransport());
  container.bind(VOICE_CONVERSATION).toConstantValue(conversation);
  container.bind(CONVERSATION_VOICE_SESSION).to(ConversationVoiceSession);
  return container.get(CONVERSATION_VOICE_SESSION);
}
