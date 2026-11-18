import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AutoArchiveSettingsDialog } from "./AutoArchiveSettingsDialog";

describe("AutoArchiveSettingsDialog", () => {
  it("saves a custom inactivity threshold", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(true);

    render(
      <AutoArchiveSettingsDialog
        channel={{
          id: "channel-1",
          name: "personal",
          channelType: "personal",
          starred: true,
          repositories: [],
          createdBy: null,
          autoArchiveAfterDays: null,
        }}
        open
        onOpenChange={vi.fn()}
        onSave={onSave}
        isSaving={false}
      />,
    );

    await user.click(
      screen.getByRole("switch", { name: "Auto-archive inactive tasks" }),
    );
    await user.click(
      screen.getByRole("combobox", { name: "Inactivity period" }),
    );
    await user.click(await screen.findByRole("option", { name: "Custom…" }));
    await user.type(
      screen.getByRole("textbox", {
        name: "Days of inactivity before auto-archive",
      }),
      "45",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith(45);
  });
});
