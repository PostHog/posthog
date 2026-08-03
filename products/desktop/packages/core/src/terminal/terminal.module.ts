import { ContainerModule } from "inversify";
import { SHELL_PROCESS_POLLER } from "./identifiers";
import { ShellProcessPoller } from "./shellProcessPoller";

export const terminalCoreModule = new ContainerModule(({ bind }) => {
  bind(ShellProcessPoller).toSelf().inSingletonScope();
  bind(SHELL_PROCESS_POLLER).toService(ShellProcessPoller);
});
