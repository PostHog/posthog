import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockSelectAttachments = vi.hoisted(() => vi.fn());
const mockDownscaleImageFile = vi.hoisted(() => vi.fn());

vi.mock("@posthog/quill", () => ({
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" {...props}>
      {children}
    </button>
  ),
  DropdownMenu: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  DropdownMenuTrigger: ({ render }: { render: React.ReactElement }) => render,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DropdownMenuItem: ({
    children,
    onClick,
    disabled,
    title,
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" onClick={onClick} disabled={disabled} title={title}>
      {children}
    </button>
  ),
  Combobox: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ComboboxContent: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  ComboboxEmpty: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  ComboboxInput: () => <input type="text" />,
  ComboboxItem: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  ComboboxList: () => null,
}));

vi.mock("../hostApi", () => ({
  selectAttachments: mockSelectAttachments,
  getGhStatus: vi.fn(),
  searchGithubRefs: vi.fn(),
  filePersistHost: {
    saveClipboardImage: vi.fn(),
    saveClipboardText: vi.fn(),
    saveClipboardFile: vi.fn(),
    downscaleImageFile: mockDownscaleImageFile,
  },
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: undefined }),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: {
    error: vi.fn(),
  },
}));

import { AttachmentMenu } from "./AttachmentMenu";

describe("AttachmentMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("inserts file and folder chips from the OS picker", async () => {
    const user = userEvent.setup();
    const onInsertChip = vi.fn();

    mockSelectAttachments.mockResolvedValue([
      { path: "/tmp/demo/test.txt", kind: "file" },
      { path: "/tmp/demo/src", kind: "directory" },
    ]);

    render(
      <Theme>
        <AttachmentMenu onAddAttachment={vi.fn()} onInsertChip={onInsertChip} />
      </Theme>,
    );

    await user.click(screen.getByText("Add file or folder"));

    expect(mockSelectAttachments).toHaveBeenCalledOnce();
    expect(mockSelectAttachments).toHaveBeenCalledWith({ mode: "both" });
    expect(onInsertChip).toHaveBeenNthCalledWith(1, {
      type: "file",
      id: "/tmp/demo/test.txt",
      label: "demo/test.txt",
    });
    expect(onInsertChip).toHaveBeenNthCalledWith(2, {
      type: "folder",
      id: "/tmp/demo/src",
      label: "demo/src",
    });
  });

  it("downscales image files from the OS picker and adds as attachment", async () => {
    const user = userEvent.setup();
    const onAddAttachment = vi.fn();
    const onInsertChip = vi.fn();

    mockSelectAttachments.mockResolvedValue([
      { path: "/tmp/demo/photo.png", kind: "file" },
      { path: "/tmp/demo/readme.md", kind: "file" },
    ]);
    mockDownscaleImageFile.mockResolvedValue({
      path: "/tmp/posthog-code-clipboard/attachment-xyz/photo.jpg",
      name: "photo.jpg",
      mimeType: "image/jpeg",
    });

    render(
      <Theme>
        <AttachmentMenu
          onAddAttachment={onAddAttachment}
          onInsertChip={onInsertChip}
        />
      </Theme>,
    );

    await user.click(screen.getByText("Add file or folder"));

    expect(mockDownscaleImageFile).toHaveBeenCalledWith({
      filePath: "/tmp/demo/photo.png",
    });
    expect(onAddAttachment).toHaveBeenCalledWith({
      id: "/tmp/posthog-code-clipboard/attachment-xyz/photo.jpg",
      label: "photo.jpg",
    });
    expect(onInsertChip).toHaveBeenCalledWith({
      type: "file",
      id: "/tmp/demo/readme.md",
      label: "demo/readme.md",
    });
  });
});
