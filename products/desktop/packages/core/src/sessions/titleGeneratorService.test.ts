import type { LlmGatewayService } from "@posthog/core/llm-gateway/llm-gateway";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FileReadClient } from "./titleGeneratorIdentifiers";
import { TitleGeneratorService } from "./titleGeneratorService";

const readAbsoluteFile = vi.fn<FileReadClient["readAbsoluteFile"]>();
const prompt = vi.fn();

function makeService(): TitleGeneratorService {
  const gateway = { prompt } as unknown as LlmGatewayService;
  const fileReadClient: FileReadClient = { readAbsoluteFile };
  return new TitleGeneratorService(gateway, fileReadClient, {
    error: vi.fn(),
  });
}

describe("enrichDescriptionWithFileContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns description unchanged when it contains real text", async () => {
    const description = "Fix the login bug";
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe(description);
    expect(readAbsoluteFile).not.toHaveBeenCalled();
  });

  it("reads text file content when description only has file tags", async () => {
    readAbsoluteFile.mockResolvedValue("const x = 1;\nexport default x;");
    const description = '1. <file path="/tmp/code.ts" />';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe("const x = 1;\nexport default x;");
    expect(readAbsoluteFile).toHaveBeenCalledWith("/tmp/code.ts");
  });

  it("handles multiple file tags", async () => {
    readAbsoluteFile
      .mockResolvedValueOnce("file one")
      .mockResolvedValueOnce("file two");

    const description =
      '1. <file path="/tmp/a.ts" />\n2. <file path="/tmp/b.ts" />';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe("file one\n\nfile two");
  });

  it("uses filePaths argument over parsed tags", async () => {
    readAbsoluteFile.mockResolvedValue("from explicit path");
    const description = '1. <file path="/tmp/ignored.ts" />';
    const result = await makeService().enrichDescriptionWithFileContent(
      description,
      ["/tmp/explicit.ts"],
    );
    expect(result).toBe("from explicit path");
    expect(readAbsoluteFile).toHaveBeenCalledWith("/tmp/explicit.ts");
  });

  it.each([
    {
      label: "binary file",
      description: '1. <file path="/tmp/screenshot.png" />',
      setup: () => {},
    },
    {
      label: "read throws",
      description: '1. <file path="/tmp/missing.ts" />',
      setup: () => readAbsoluteFile.mockRejectedValue(new Error("ENOENT")),
    },
    {
      label: "read returns null",
      description: '1. <file path="/tmp/empty.ts" />',
      setup: () => readAbsoluteFile.mockResolvedValue(null),
    },
  ])(
    "falls back to filename hint -- $label",
    async ({ description, setup }) => {
      setup();
      const result =
        await makeService().enrichDescriptionWithFileContent(description);
      const filename = description.match(/path="[^"]*\/([^"]+)"/)?.[1];
      expect(result).toBe(`[Attached: ${filename}]`);
    },
  );

  it.each([
    {
      label: "cloud description summary",
      description: "Attached files: pasted-text.txt",
    },
    {
      label: "numbered prompt list item",
      description: "1. [Attached files: pasted-text.txt]",
    },
  ])(
    "reads explicit file paths for attachment-only prompt -- $label",
    async ({ description }) => {
      readAbsoluteFile.mockResolvedValue(
        "Refactor the auth flow and add tests",
      );
      const result = await makeService().enrichDescriptionWithFileContent(
        description,
        ["/tmp/clip/pasted-text.txt"],
      );
      expect(result).toBe("Refactor the auth flow and add tests");
      expect(readAbsoluteFile).toHaveBeenCalledWith(
        "/tmp/clip/pasted-text.txt",
      );
    },
  );

  it("ignores explicit file paths when the prompt has real typed text", async () => {
    const description = "Fix the login bug\n\nAttached files: pasted-text.txt";
    const result = await makeService().enrichDescriptionWithFileContent(
      description,
      ["/tmp/clip/pasted-text.txt"],
    );
    expect(result).toBe(description);
    expect(readAbsoluteFile).not.toHaveBeenCalled();
  });

  it("does not strip user text that starts with 'Attached files:' but has no brackets", async () => {
    // "1. Attached files: xyz" (no brackets) is user-typed text, not a sentinel.
    const description = "1. Attached files: here is my task\n2. please fix it";
    const result = await makeService().enrichDescriptionWithFileContent(
      description,
      ["/tmp/clip/pasted-text.txt"],
    );
    expect(result).toBe(description);
    expect(readAbsoluteFile).not.toHaveBeenCalled();
  });

  it("truncates content longer than 500 chars", async () => {
    const longContent = "x".repeat(600);
    readAbsoluteFile.mockResolvedValue(longContent);
    const description = '1. <file path="/tmp/big.ts" />';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe("x".repeat(500));
  });

  it("strips 'Attached files:' lines when checking for real text", async () => {
    readAbsoluteFile.mockResolvedValue("content");
    const description = '1. <file path="/tmp/a.ts" />\nAttached files: a.ts';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe("content");
  });

  it("returns original description when no file paths found", async () => {
    const description = "1. \n2. ";
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe(description);
  });

  it("mixes binary and text files", async () => {
    readAbsoluteFile.mockResolvedValue("text content");
    const result = await makeService().enrichDescriptionWithFileContent("", [
      "/tmp/image.jpg",
      "/tmp/code.ts",
    ]);
    expect(result).toBe("[Attached: image.jpg]\n\ntext content");
  });

  it("returns description unchanged for folder-only input", async () => {
    const description = '<folder path="src/components" />';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe(description);
    expect(readAbsoluteFile).not.toHaveBeenCalled();
  });

  it("reads file and drops folder for mixed file+folder input", async () => {
    readAbsoluteFile.mockResolvedValue("file body");
    const description =
      '<file path="/tmp/a.ts" /><folder path="src/components" />';
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe("file body");
    expect(readAbsoluteFile).toHaveBeenCalledTimes(1);
    expect(readAbsoluteFile).toHaveBeenCalledWith("/tmp/a.ts");
  });

  it("treats non-chip XML-like text as real content", async () => {
    const description = "<div>hello world</div>";
    const result =
      await makeService().enrichDescriptionWithFileContent(description);
    expect(result).toBe(description);
    expect(readAbsoluteFile).not.toHaveBeenCalled();
  });
});

describe("generateTitleAndSummary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("truncates title to 255 chars", async () => {
    const longTitle = "A".repeat(300);
    prompt.mockResolvedValue({
      content: `TITLE: ${longTitle}\nSUMMARY: A summary`,
    });

    const result = await makeService().generateTitleAndSummary("some content");
    expect(result?.title).toHaveLength(255);
    expect(result?.summary).toBe("A summary");
  });

  it("strips surrounding quotes from title", async () => {
    prompt.mockResolvedValue({
      content: 'TITLE: "Fix login bug"\nSUMMARY: Fixing auth',
    });

    const result =
      await makeService().generateTitleAndSummary("fix the login bug");
    expect(result?.title).toBe("Fix login bug");
  });

  it("returns null on error", async () => {
    prompt.mockRejectedValue(new Error("network error"));
    const result = await makeService().generateTitleAndSummary("some content");
    expect(result).toBeNull();
  });
});
