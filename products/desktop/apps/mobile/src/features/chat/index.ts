// Shared chat-style UI primitives reused by tasks and inbox. The standalone
// PostHog AI conversations feature has been removed, but these components
// (markdown rendering, tool-call display, agent/human bubbles, voice input)
// are still used elsewhere.

// Components
export { AgentMessage } from "./components/AgentMessage";
export {
  HumanMessage,
  type HumanMessageAttachment,
  MessageFileChip,
} from "./components/HumanMessage";
export { MarkdownImage } from "./components/MarkdownImage";
export { MarkdownText } from "./components/MarkdownText";
export type {
  ToolKind,
  ToolMessageProps,
  ToolStatus,
} from "./components/ToolMessage";
export { deriveToolKind, ToolMessage } from "./components/ToolMessage";

// Hooks
export { usePeriodicRerender } from "./hooks/usePeriodicRerender";
export { useVoiceRecording } from "./hooks/useVoiceRecording";
