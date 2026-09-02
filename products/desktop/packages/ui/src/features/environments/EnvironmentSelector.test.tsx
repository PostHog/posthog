import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const useEnvironments = vi.fn();

vi.mock("./useEnvironments", () => ({
  useEnvironments: (repoPath: string | null) => useEnvironments(repoPath),
}));

import { EnvironmentSelector } from "./EnvironmentSelector";

describe("EnvironmentSelector", () => {
  it("never selects a repo-provided environment on its own", () => {
    useEnvironments.mockReturnValue({
      data: [
        { id: "env-1", name: "Malicious" },
        { id: "env-2", name: "Other" },
      ],
    });
    const onChange = vi.fn();

    render(
      <EnvironmentSelector repoPath="/repo" value={null} onChange={onChange} />,
    );

    expect(onChange).not.toHaveBeenCalled();
  });
});
