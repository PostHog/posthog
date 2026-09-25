import { ContainerModule } from "inversify";
import {
  CODEX_CLOUD_ACCOUNT_SERVICE,
  CodexCloudAccountService,
} from "./codexCloudAccountService";

export const codexCloudAccountModule = new ContainerModule(({ bind }) => {
  bind(CODEX_CLOUD_ACCOUNT_SERVICE)
    .to(CodexCloudAccountService)
    .inSingletonScope();
});
