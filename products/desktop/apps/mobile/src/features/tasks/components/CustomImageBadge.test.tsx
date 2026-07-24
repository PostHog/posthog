import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Task, TaskRun } from "../types";

const { mockUseAuthStore, mockGetImages, mockGetEnvironments } = vi.hoisted(
  () => ({
    mockUseAuthStore: vi.fn(),
    mockGetImages: vi.fn(),
    mockGetEnvironments: vi.fn(),
  }),
);

vi.mock("@/features/auth", () => ({ useAuthStore: mockUseAuthStore }));

vi.mock("../api", () => ({
  getSandboxCustomImages: mockGetImages,
  getSandboxEnvironments: mockGetEnvironments,
}));

vi.mock("phosphor-react-native", () => ({
  Cube: (props: Record<string, unknown>) => createElement("Cube", props),
}));

vi.mock("@/lib/theme", () => ({
  toRgba: (hex: string, alpha: number) => `${hex}/${alpha}`,
}));

import { CustomImageBadge } from "./CustomImageBadge";

function makeTask(run: Partial<TaskRun> | undefined): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Task",
    description: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    origin_product: "user_created",
    latest_run: run
      ? ({
          id: "run-1",
          task: "task-1",
          team: 1,
          branch: null,
          status: "completed",
          log_url: "",
          error_message: null,
          output: null,
          state: {},
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          completed_at: null,
          ...run,
        } as TaskRun)
      : undefined,
  };
}

async function render(task: Task) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  let renderer: ReturnType<typeof create> | null = null;
  await act(async () => {
    renderer = create(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(CustomImageBadge, { task }),
      ),
    );
  });
  // Flush pending react-query resolutions so a resolved image name renders.
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

function label(renderer: ReturnType<typeof create>): string | undefined {
  const node = renderer.root.findAll(
    (n) => typeof n.props?.accessibilityLabel === "string",
  )[0];
  return node?.props.accessibilityLabel as string | undefined;
}

describe("CustomImageBadge", () => {
  beforeEach(() => {
    mockUseAuthStore.mockReturnValue({
      projectId: 1,
      oauthAccessToken: "token",
    });
    mockGetImages.mockReset();
    mockGetEnvironments.mockReset();
    mockGetImages.mockResolvedValue([]);
    mockGetEnvironments.mockResolvedValue([]);
  });

  it("renders nothing for a local run", async () => {
    const r = await render(
      makeTask({ environment: "local", state: { custom_image_id: "img-1" } }),
    );
    expect(r.toJSON()).toBeNull();
    expect(mockGetImages).not.toHaveBeenCalled();
  });

  it("renders nothing for a cloud run without a custom image id", async () => {
    const r = await render(makeTask({ environment: "cloud", state: {} }));
    expect(r.toJSON()).toBeNull();
    expect(mockGetImages).not.toHaveBeenCalled();
  });

  it("resolves the image name from a direct custom_image_id", async () => {
    mockGetImages.mockResolvedValue([{ id: "img-1", name: "My Image" }]);
    const r = await render(
      makeTask({ environment: "cloud", state: { custom_image_id: "img-1" } }),
    );
    expect(label(r)).toBe('Runs on custom base image "My Image"');
  });

  it("resolves the image name via sandbox_environment_id", async () => {
    mockGetEnvironments.mockResolvedValue([
      { id: "env-1", custom_image_id: "img-2", custom_image_name: null },
    ]);
    mockGetImages.mockResolvedValue([{ id: "img-2", name: "Env Image" }]);
    const r = await render(
      makeTask({
        environment: "cloud",
        state: { sandbox_environment_id: "env-1" },
      }),
    );
    expect(label(r)).toBe('Runs on custom base image "Env Image"');
  });

  it("renders nothing when the image cannot be resolved", async () => {
    mockGetImages.mockResolvedValue([{ id: "other", name: "Other" }]);
    const r = await render(
      makeTask({ environment: "cloud", state: { custom_image_id: "missing" } }),
    );
    expect(r.toJSON()).toBeNull();
  });
});
