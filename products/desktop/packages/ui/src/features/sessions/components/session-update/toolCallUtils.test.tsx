import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ContentPre } from "./toolCallUtils";

describe("ContentPre", () => {
  it("renders output under the cap in full, with no reveal button", () => {
    render(<ContentPre>{"short output"}</ContentPre>);

    expect(screen.getByText("short output")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("caps oversized output and reveals the rest on request", async () => {
    const text = `${"a".repeat(60_000)}END`;
    const { container } = render(<ContentPre>{text}</ContentPre>);

    const pre = container.querySelector("pre");
    expect(pre?.textContent?.length).toBeLessThan(51_000);
    expect(pre?.textContent?.includes("END")).toBe(false);

    await userEvent.click(
      screen.getByRole("button", { name: "Show full output" }),
    );

    expect(container.querySelector("pre")?.textContent?.endsWith("END")).toBe(
      true,
    );
  });
});
