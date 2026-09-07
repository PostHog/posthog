/**
 * In-flight attachment held by the composer until the message is sent.
 * `uri` points at the picker's local file (e.g. ph://… or file://…). Bytes are
 * read lazily at send-time so we never hold large base64 strings in memory.
 */
export type PendingAttachment =
  | {
      kind: "image";
      id: string;
      uri: string;
      fileName: string;
      mimeType: string;
      sizeBytes?: number;
    }
  | {
      kind: "document";
      id: string;
      uri: string;
      fileName: string;
      mimeType: string;
      sizeBytes?: number;
    };

/**
 * Minimal subset of `@agentclientprotocol/sdk`'s `ContentBlock` that the
 * backend's `deserializeCloudPrompt` accepts. We mirror the wire shape rather
 * than depending on the ACP SDK from the mobile bundle.
 */
export type CloudPromptBlock =
  | { type: "text"; text: string }
  | { type: "image"; data: string; mimeType: string; uri?: string }
  | {
      type: "resource";
      resource: {
        uri: string;
        text: string;
        mimeType: string;
      };
    };
