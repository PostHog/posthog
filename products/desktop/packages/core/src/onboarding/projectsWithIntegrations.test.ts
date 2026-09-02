import { describe, expect, it } from "vitest";
import { deriveProjectsWithIntegrations } from "./projectsWithIntegrations";

const project = (id: number, name: string) => ({
  id,
  name,
  organization: { id: "org", name: "Org" },
});

describe("deriveProjectsWithIntegrations", () => {
  it("sorts projects by name and derives hasGithubIntegration", () => {
    const projects = [project(1, "Beta"), project(2, "Alpha")];
    const integrations = [[{ kind: "slack" }], [{ kind: "github" }]];

    const result = deriveProjectsWithIntegrations(projects, integrations);

    expect(result.projects.map((p) => p.name)).toEqual(["Alpha", "Beta"]);
    expect(result.projects[0].hasGithubIntegration).toBe(true);
    expect(result.projects[1].hasGithubIntegration).toBe(false);
  });

  it("filters projects with github into projectsWithGithub", () => {
    const projects = [project(1, "Alpha"), project(2, "Beta")];
    const integrations = [[{ kind: "github" }], []];

    const result = deriveProjectsWithIntegrations(projects, integrations);

    expect(result.projectsWithGithub.map((p) => p.id)).toEqual([1]);
  });

  it("treats missing integration data as empty", () => {
    const result = deriveProjectsWithIntegrations(
      [project(1, "Alpha")],
      [undefined],
    );
    expect(result.projects[0].integrations).toEqual([]);
    expect(result.projects[0].hasGithubIntegration).toBe(false);
  });
});
