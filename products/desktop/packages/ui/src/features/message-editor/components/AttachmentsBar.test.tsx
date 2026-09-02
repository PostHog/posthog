import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AttachmentsBar } from "./AttachmentsBar";

describe("AttachmentsBar", () => {
  it("shows upload state for each attachment", () => {
    render(
      <Theme>
        <AttachmentsBar
          attachments={[
            { id: "/tmp/uploading.txt", label: "uploading.txt" },
            { id: "/tmp/failed.txt", label: "failed.txt" },
          ]}
          onRemove={vi.fn()}
          uploadStatuses={{
            "/tmp/uploading.txt": "uploading",
            "/tmp/failed.txt": "error",
          }}
        />
      </Theme>,
    );

    expect(screen.getByLabelText("Uploading attachment")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Attachment upload failed"),
    ).toBeInTheDocument();
  });
});
