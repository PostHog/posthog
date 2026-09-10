import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PiExtensionDialog } from "./PiExtensionDialog";
import { PiExtensionStatuses, PiExtensionWidgets } from "./PiExtensionSurfaces";
import { buildPiExtensionResponse } from "./piExtensionResponse";

describe("Pi extension presenters", () => {
  it("builds matching response wire shapes", () => {
    expect(
      buildPiExtensionResponse(
        {
          type: "extension_ui_request",
          id: "confirm-1",
          method: "confirm",
          title: "Continue?",
          message: "Proceed?",
        },
        true,
      ),
    ).toEqual({
      type: "extension_ui_response",
      id: "confirm-1",
      confirmed: true,
    });
    expect(
      buildPiExtensionResponse(
        {
          type: "extension_ui_request",
          id: "confirm-2",
          method: "confirm",
          title: "Continue?",
          message: "Proceed?",
        },
        false,
      ),
    ).toEqual({
      type: "extension_ui_response",
      id: "confirm-2",
      confirmed: false,
    });
    expect(
      buildPiExtensionResponse(
        {
          type: "extension_ui_request",
          id: "editor-1",
          method: "editor",
          title: "Edit",
        },
        "updated",
      ),
    ).toEqual({
      type: "extension_ui_response",
      id: "editor-1",
      value: "updated",
    });
  });

  it("submits labelled input with Enter and allows retry after failure", async () => {
    const user = userEvent.setup();
    const onRespond = vi
      .fn<() => Promise<void>>()
      .mockRejectedValueOnce(new Error("wire failed"))
      .mockResolvedValueOnce();
    const onCancel = vi.fn(async () => {});

    render(
      <PiExtensionDialog
        request={{
          type: "extension_ui_request",
          id: "input-1",
          method: "input",
          title: "Your name",
          placeholder: "Name",
        }}
        onRespond={onRespond}
        onCancel={onCancel}
      />,
    );

    const input = screen.getByLabelText("Response");
    await user.type(input, "Ada{Enter}");
    await waitFor(() => expect(onRespond).toHaveBeenCalledTimes(1));
    expect(onRespond).toHaveBeenLastCalledWith({
      type: "extension_ui_response",
      id: "input-1",
      value: "Ada",
    });

    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(onRespond).toHaveBeenCalledTimes(2);
  });

  it("submits an explicit negative confirmation", async () => {
    const onRespond = vi.fn(async () => {});

    render(
      <PiExtensionDialog
        request={{
          type: "extension_ui_request",
          id: "confirm-1",
          method: "confirm",
          title: "Continue?",
          message: "Proceed?",
        }}
        onRespond={onRespond}
        onCancel={vi.fn(async () => {})}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(onRespond).toHaveBeenCalledWith({
      type: "extension_ui_response",
      id: "confirm-1",
      confirmed: false,
    });
  });

  it("guards concurrent cancellation while delivery is pending", async () => {
    let resolveCancel: () => void = () => {};
    const onCancel = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveCancel = resolve;
        }),
    );

    render(
      <PiExtensionDialog
        request={{
          type: "extension_ui_request",
          id: "confirm-1",
          method: "confirm",
          title: "Continue?",
          message: "Proceed?",
        }}
        onRespond={vi.fn(async () => {})}
        onCancel={onCancel}
      />,
    );

    const form = screen.getByRole("form", { name: "Continue? response" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.submit(form);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Submitting…" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    resolveCancel();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Confirm" })).toHaveAttribute(
        "aria-disabled",
        "false",
      ),
    );
  });

  it("keeps Enter as a newline in the multiline editor", async () => {
    const user = userEvent.setup();
    const onRespond = vi.fn(async () => {});

    render(
      <PiExtensionDialog
        request={{
          type: "extension_ui_request",
          id: "editor-1",
          method: "editor",
          title: "Edit response",
          prefill: "first",
        }}
        onRespond={onRespond}
        onCancel={vi.fn(async () => {})}
      />,
    );

    const editor = screen.getByLabelText("Response");
    await user.click(editor);
    await user.keyboard("{Enter}second");

    expect(onRespond).not.toHaveBeenCalled();
    expect(editor).toHaveValue("first\nsecond");
  });

  it("renders compact statuses and only widgets for the requested placement", () => {
    render(
      <>
        <PiExtensionStatuses statuses={{ build: "Running" }} />
        <PiExtensionWidgets
          placement="aboveEditor"
          widgets={{
            above: { lines: ["Above content"], placement: "aboveEditor" },
            below: { lines: ["Below content"], placement: "belowEditor" },
          }}
        />
      </>,
    );

    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("Above content")).toBeInTheDocument();
    expect(screen.queryByText("Below content")).not.toBeInTheDocument();
  });
});
