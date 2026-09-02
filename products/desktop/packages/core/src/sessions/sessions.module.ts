import { ContainerModule } from "inversify";
import { CLOUD_ARTIFACT_SERVICE } from "./cloudArtifactIdentifiers";
import { CloudArtifactService } from "./cloudArtifactService";
import { TITLE_GENERATOR_SERVICE } from "./titleGeneratorIdentifiers";
import { TitleGeneratorService } from "./titleGeneratorService";

export const sessionsModule = new ContainerModule(({ bind }) => {
  bind(CLOUD_ARTIFACT_SERVICE).to(CloudArtifactService).inSingletonScope();
  bind(TITLE_GENERATOR_SERVICE).to(TitleGeneratorService).inSingletonScope();
});
