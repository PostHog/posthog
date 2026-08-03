import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BuiltCanvas } from "./BuiltCanvas";

describe("BuiltCanvas", () => {
  it("loads an immutable artifact without granting origin or popup access", () => {
    render(
      <BuiltCanvas
        artifactUrl="https://usercontent.example/build/index.html"
        onDataRequest={vi.fn()}
      />,
    );

    expect(screen.getByTitle("Canvas")).toHaveAttribute(
      "src",
      "https://usercontent.example/build/index.html",
    );
    expect(screen.getByTitle("Canvas")).toHaveAttribute(
      "sandbox",
      "allow-scripts",
    );
    expect(screen.getByTitle("Canvas")).toHaveAttribute(
      "referrerpolicy",
      "no-referrer",
    );
  });
});
