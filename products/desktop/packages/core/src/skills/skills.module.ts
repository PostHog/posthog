import { ContainerModule } from "inversify";
import { TEAM_SKILLS_SERVICE } from "./identifiers";
import { TeamSkillsService } from "./teamSkillsService";

export const skillsCoreModule = new ContainerModule(({ bind }) => {
  bind(TEAM_SKILLS_SERVICE).to(TeamSkillsService).inSingletonScope();
});
