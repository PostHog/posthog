import { PackageIcon } from "@phosphor-icons/react";
import type { Task } from "@posthog/shared/domain-types";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Tab } from "../panelTypes";
import { useTabInjection } from "./usePanelLayoutHooks";

vi.mock("../../actions/ActionTabIcon", () => ({
  ActionTabIcon: () => null,
}));

vi.mock("../../sidebar/useCwd", () => ({
  useCwd: () => null,
}));

vi.mock("../../task-detail/components/TabContentRenderer", () => ({
  TabContentRenderer: () => null,
}));

describe("useTabInjection", () => {
  it("uses the artifact icon instead of inferring an icon from an artifact name", () => {
    const tabs: Tab[] = [
      {
        id: "artifact-reference-1",
        label: "export.sql",
        data: {
          type: "artifact",
          runId: "run-1",
          artifactId: "reference-1",
        },
      },
    ];

    const { result } = renderHook(() =>
      useTabInjection(tabs, "main-panel", "task-1", {} as Task, vi.fn()),
    );

    expect(result.current[0].icon).toMatchObject({ type: PackageIcon });
  });
});
