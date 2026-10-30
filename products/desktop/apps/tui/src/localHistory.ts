import { existsSync, readFileSync } from "node:fs";
import {
  parseSessionEntries,
  type SessionEntry,
} from "@earendil-works/pi-coding-agent";
import { getRemotePiConversation } from "@posthog/agent/pi/remote-rpc-client";
import { asEntry } from "./local";
import type { LocalChats } from "./localChats";
import { emptyRunView, type RunView } from "./runs";

// A local chat's saved conversation, read from its files on disk, so showing the chat never starts its agent.
export async function localHistory(
  chats: LocalChats,
  id: string,
): Promise<RunView | null> {
  const harness = chats.harnessOf(id);
  if (harness === "claude") {
    return {
      ...emptyRunView,
      loaded: true,
      local: true,
      entries: chats.acpLog(id).load().entries,
    };
  }
  const file = chats.sessionFile(id);
  if (harness === null || !existsSync(file)) return null;
  // The same translation the running agent's entries get, over the file's entries in append order.
  const entries = parseSessionEntries(readFileSync(file, "utf8")).filter(
    (entry): entry is SessionEntry => entry.type !== "session",
  );
  const history = await getRemotePiConversation({
    getEntries: async () => ({ entries, leafId: null }),
  });
  return {
    ...emptyRunView,
    loaded: true,
    local: true,
    entries: history.map(asEntry),
  };
}
