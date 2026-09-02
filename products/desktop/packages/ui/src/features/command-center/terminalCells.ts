import { getTerminalCellId } from "@posthog/core/command-center/grid";
import { destroyShellTerminal } from "../terminal/destroyShellTerminal";

export function getTerminalCellStateKey(terminalId: string): string {
  return `cc-terminal-${terminalId}`;
}

export function destroyTerminalCells(cellValues: (string | null)[]): void {
  for (const value of cellValues) {
    const terminalId = getTerminalCellId(value);
    if (terminalId) {
      destroyShellTerminal(getTerminalCellStateKey(terminalId));
    }
  }
}
