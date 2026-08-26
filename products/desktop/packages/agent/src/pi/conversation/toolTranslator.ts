import type { ImageContent, TextContent } from "@earendil-works/pi-ai";
import type {
  AgentToolCallContent,
  AgentToolCallLocation,
} from "@posthog/shared";

export interface PiToolTranslatorInput {
  toolCallId: string;
  arguments: unknown;
  resultContent?: (TextContent | ImageContent)[];
  details?: unknown;
  isError?: boolean;
}

export interface PiToolTranslatorOutput {
  locations?: AgentToolCallLocation[];
  content?: AgentToolCallContent[];
}

export type PiToolTranslator = (
  input: PiToolTranslatorInput,
) => PiToolTranslatorOutput;
