import { track } from "../analytics";
import { messageOf } from "../errors";
import { findPane, type LayoutState } from "../layout";
import {
  addMcpServer,
  localMcpServers,
  MCP_AUTHS,
  type McpClient,
  mcpAuthSheet,
  mcpSheet,
  mcpTextSheet,
  reauthorizeMcpServer,
} from "../mcp";
import { openUrl } from "../openUrl";
import { loadPrefs, savePrefs } from "../prefs";
import type { Sheet } from "../sheet";
import type { Notice } from "./useNotice";

export interface McpSheet {
  // The account's servers and this machine's, with their sign-in state and the relay switch.
  open: (paneId: string) => void;
  // Adds a custom server to the account: its name, its URL, and how it signs in, one sheet each.
  addServer: (paneId: string) => Promise<void>;
}

// `/mcp` and `/mcp add`.
export function useMcpSheet({
  layout,
  openModal,
  closeModal,
  notice: { flashNotice, showNotice },
  mcp,
}: {
  layout: LayoutState;
  openModal: (
    paneId: string,
    sheet: Sheet,
    choose: (index: number, text?: string) => void,
    dismiss?: () => void,
  ) => void;
  closeModal: (paneId: string) => void;
  notice: Notice;
  // The account's MCP servers; absent while signed out.
  mcp?: McpClient;
}): McpSheet {
  // A typed answer, or a pick, on a sheet of its own; Esc ends the questions.
  const askText = (paneId: string, sheet: Sheet): Promise<string> =>
    new Promise((resolve, reject) =>
      openModal(
        paneId,
        sheet,
        (_, text = "") => resolve(text.trim()),
        () => reject(new Error("cancelled")),
      ),
    );
  const pickIndex = (paneId: string, sheet: Sheet): Promise<number> =>
    new Promise((resolve, reject) =>
      openModal(paneId, sheet, resolve, () => reject(new Error("cancelled"))),
    );

  const addServer = async (paneId: string): Promise<void> => {
    const here = { taskId: findPane(layout, paneId)?.taskId ?? null };
    if (!mcp) return;
    try {
      const name = await askText(
        paneId,
        mcpTextSheet("Add an MCP server", "What is it called?", "Linear"),
      );
      if (!name) return;
      const url = await askText(
        paneId,
        mcpTextSheet(
          `Add ${name}`,
          "Its MCP URL.",
          "https://mcp.example.com/mcp",
        ),
      );
      if (!url) return;
      const auth = MCP_AUTHS[await pickIndex(paneId, mcpAuthSheet())].id;
      const apiKey =
        auth === "api_key"
          ? await askText(
              paneId,
              mcpTextSheet(`Add ${name}`, "Its API key.", ""),
            )
          : undefined;
      if (auth === "oauth")
        showNotice(`Finish signing in to ${name} with your browser…`);
      track("mcp server added", { auth });
      const added = await addMcpServer(
        mcp,
        { name, url, auth, apiKey },
        openUrl,
      );
      flashNotice(
        `Added ${added.display_name || added.name}: new chats reach it`,
        here,
      );
    } catch (error) {
      if (messageOf(error) !== "cancelled")
        flashNotice(`Couldn't add the server: ${messageOf(error)}`, here);
    }
  };

  // The account's servers come from the server; this machine's are read as the sheet opens, so an edit to
  // ~/.claude.json shows on the next /mcp.
  const open = (paneId: string): void => {
    const here = { taskId: findPane(layout, paneId)?.taskId ?? null };
    if (!mcp) {
      flashNotice("Sign in first: type /login", here);
      return;
    }
    mcp.installations().then(
      (installations) => {
        const sheet = mcpSheet(installations, localMcpServers(), {
          relay: loadPrefs().relayLocalMcp,
        });
        openModal(paneId, sheet, (index) => {
          closeModal(paneId);
          const stale = sheet.reauth.get(index);
          if (stale) {
            showNotice(
              `Finish signing in to ${stale.display_name || stale.name} with your browser…`,
            );
            reauthorizeMcpServer(mcp, stale, openUrl).then(
              (signedIn) =>
                flashNotice(
                  `${signedIn.display_name || signedIn.name} signed in again`,
                  here,
                ),
              (error: unknown) =>
                flashNotice(
                  `Couldn't sign in again: ${messageOf(error)}`,
                  here,
                ),
            );
            return;
          }
          if (index === sheet.addServer) {
            void addServer(paneId);
            return;
          }
          if (index !== sheet.relayToggle) return;
          const relay = !loadPrefs().relayLocalMcp;
          savePrefs({ relayLocalMcp: relay });
          track("mcp relay switched", { on: relay });
          flashNotice(
            relay
              ? "New cloud Claude Code and Codex chats reach this machine's MCP servers while the TUI is open"
              : "New cloud chats no longer reach this machine's MCP servers",
            here,
          );
        });
      },
      (error: unknown) =>
        flashNotice(`Couldn't list MCP servers: ${messageOf(error)}`, here),
    );
  };

  return { open, addServer };
}
