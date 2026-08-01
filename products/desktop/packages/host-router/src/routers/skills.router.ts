import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { SKILLS_SERVICE } from "@posthog/workspace-server/services/skills/identifiers";
import {
  bundleLocalSkillInput,
  bundleLocalSkillOutput,
  createSkillInput,
  deleteSkillFileInput,
  deleteSkillInput,
  exportSkillInput,
  exportSkillOutput,
  importCodexSkillInput,
  installTeamSkillInput,
  listSkillsOutput,
  readSkillFileInput,
  readSkillFileOutput,
  renameSkillFileInput,
  resolveSkillDependenciesInput,
  resolveSkillDependenciesOutput,
  saveSkillFileInput,
  saveSkillManifestInput,
  skillContentsInput,
  skillContentsOutput,
  skillPathOutput,
} from "@posthog/workspace-server/services/skills/schemas";
import type { SkillsService } from "@posthog/workspace-server/services/skills/skills";
import { SKILLS_MARKETPLACE_SERVICE } from "@posthog/workspace-server/services/skills-marketplace/identifiers";
import {
  marketplaceInstallInput,
  marketplaceInstallOutput,
  marketplacePreviewOutput,
  marketplaceSearchInput,
  marketplaceSearchOutput,
  marketplaceSkillRef,
} from "@posthog/workspace-server/services/skills-marketplace/schemas";
import type { SkillsMarketplaceService } from "@posthog/workspace-server/services/skills-marketplace/skills-marketplace";

export const skillsRouter = router({
  list: publicProcedure
    .output(listSkillsOutput)
    .query(({ ctx }) =>
      ctx.container.get<SkillsService>(SKILLS_SERVICE).listSkills(),
    ),
  bundleLocal: publicProcedure
    .input(bundleLocalSkillInput)
    .output(bundleLocalSkillOutput)
    .query(({ ctx, input }) =>
      ctx.container.get<SkillsService>(SKILLS_SERVICE).bundleLocalSkill(input),
    ),
  resolveDependencies: publicProcedure
    .input(resolveSkillDependenciesInput)
    .output(resolveSkillDependenciesOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<SkillsService>(SKILLS_SERVICE)
        .resolveSkillBundleDependencies(input),
    ),
  contents: publicProcedure
    .input(skillContentsInput)
    .output(skillContentsOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<SkillsService>(SKILLS_SERVICE)
        .getSkillContents(input.skillPath),
    ),
  readFile: publicProcedure
    .input(readSkillFileInput)
    .output(readSkillFileOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<SkillsService>(SKILLS_SERVICE)
        .readSkillFile(input.skillPath, input.filePath),
    ),
  create: publicProcedure
    .input(createSkillInput)
    .output(skillPathOutput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<SkillsService>(SKILLS_SERVICE).createSkill(input),
    ),
  saveManifest: publicProcedure
    .input(saveSkillManifestInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<SkillsService>(SKILLS_SERVICE)
        .saveSkillManifest(input.skillPath, input),
    ),
  saveFile: publicProcedure
    .input(saveSkillFileInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<SkillsService>(SKILLS_SERVICE)
        .saveSkillFile(input.skillPath, input.filePath, input.content),
    ),
  renameFile: publicProcedure
    .input(renameSkillFileInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<SkillsService>(SKILLS_SERVICE)
        .renameSkillFile(input.skillPath, input.fromPath, input.toPath),
    ),
  deleteFile: publicProcedure
    .input(deleteSkillFileInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<SkillsService>(SKILLS_SERVICE)
        .deleteSkillFile(input.skillPath, input.filePath),
    ),
  delete: publicProcedure
    .input(deleteSkillInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<SkillsService>(SKILLS_SERVICE)
        .deleteSkill(input.skillPath),
    ),
  export: publicProcedure
    .input(exportSkillInput)
    .output(exportSkillOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<SkillsService>(SKILLS_SERVICE)
        .exportSkill(input.skillPath),
    ),
  installTeamSkill: publicProcedure
    .input(installTeamSkillInput)
    .output(skillPathOutput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<SkillsService>(SKILLS_SERVICE).installTeamSkill(input),
    ),
  importCodex: publicProcedure
    .input(importCodexSkillInput)
    .output(skillPathOutput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<SkillsService>(SKILLS_SERVICE)
        .importCodexSkill(input.skillPath, input.overwrite ?? false),
    ),
  watch: publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<SkillsService>(SKILLS_SERVICE);
    for await (const event of service.watchSkills(opts.signal)) {
      yield event;
    }
  }),
  marketplace: router({
    search: publicProcedure
      .input(marketplaceSearchInput)
      .output(marketplaceSearchOutput)
      .query(({ ctx, input }) =>
        ctx.container
          .get<SkillsMarketplaceService>(SKILLS_MARKETPLACE_SERVICE)
          .search(input.query),
      ),
    preview: publicProcedure
      .input(marketplaceSkillRef)
      .output(marketplacePreviewOutput)
      .query(({ ctx, input }) =>
        ctx.container
          .get<SkillsMarketplaceService>(SKILLS_MARKETPLACE_SERVICE)
          .preview(input),
      ),
    install: publicProcedure
      .input(marketplaceInstallInput)
      .output(marketplaceInstallOutput)
      .mutation(({ ctx, input }) =>
        ctx.container
          .get<SkillsMarketplaceService>(SKILLS_MARKETPLACE_SERVICE)
          .install(
            { source: input.source, skillId: input.skillId },
            input.overwrite ?? false,
          ),
      ),
  }),
});
