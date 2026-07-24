import { toolInfoFromToolUse } from "@posthog/agent/adapters/claude/conversion/tool-use-to-acp";
import { ToolCallBlock } from "@posthog/ui/features/sessions/components/session-update/ToolCallBlock";
import type {
  CodeToolKind,
  ToolCall,
} from "@posthog/ui/features/sessions/types";
import type { Meta, StoryObj } from "@storybook/react-vite";

function buildToolCallData(
  toolName: string,
  toolInput: Record<string, unknown>,
  overrides?: Partial<ToolCall>,
): ToolCall {
  const info = toolInfoFromToolUse({ name: toolName, input: toolInput }, {});
  return {
    toolCallId: `story-${Date.now()}-${Math.random()}`,
    title: info.title,
    kind: info.kind as CodeToolKind,
    content: info.content,
    locations: info.locations,
    rawInput: toolInput,
    status: "completed",
    ...overrides,
  };
}

const meta: Meta<typeof ToolCallBlock> = {
  title: "Features/Sessions/ToolCallBlock",
  component: ToolCallBlock,
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof ToolCallBlock>;

export const ReadFile: Story = {
  args: {
    toolCall: {
      ...buildToolCallData("Read", {
        file_path: "/Users/jonathan/dev/posthog-code/src/utils/helpers.ts",
      }),
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: `export function formatDate(date: Date): string {
  return date.toISOString().split("T")[0];
}

export function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

export function debounce<T extends (...args: unknown[]) => unknown>(
  fn: T,
  delay: number
): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout>;
  return (...args: Parameters<T>) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
}`,
          },
        },
      ],
    },
  },
};

export const ReadFileLoading: Story = {
  args: {
    toolCall: buildToolCallData(
      "Read",
      { file_path: "/Users/jonathan/dev/posthog-code/package.json" },
      { status: "in_progress" },
    ),
  },
};

export const ReadFileFailed: Story = {
  args: {
    toolCall: buildToolCallData(
      "Read",
      { file_path: "/nonexistent/file.ts" },
      { status: "failed" },
    ),
  },
};

export const ReadFileWithOffset: Story = {
  args: {
    toolCall: {
      ...buildToolCallData("Read", {
        file_path: "/Users/jonathan/dev/posthog-code/src/utils/helpers.ts",
        offset: 49,
        limit: 15,
      }),
      locations: [{ path: "src/utils/helpers.ts", line: 49 }],
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: `export function debounce<T extends (...args: unknown[]) => unknown>(
  fn: T,
  delay: number
): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout>;
  return (...args: Parameters<T>) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
}

export function throttle<T extends (...args: unknown[]) => unknown>(
  fn: T,
  limit: number
): (...args: Parameters<T>) => void {`,
          },
        },
      ],
    },
  },
};

const editInput = {
  file_path: "src/utils/helpers.ts",
  old_string: `function oldName() {
  const result = calculate();
  return result;
}`,
  new_string: `function newName() {
  const result = calculate();
  console.log("Result:", result);
  return result;
}`,
};

export const EditFile: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "Edit `src/utils/helpers.ts`",
      kind: "edit",
      status: "completed",
      rawInput: editInput,
      content: [
        {
          type: "diff",
          path: "src/utils/helpers.ts",
          oldText: editInput.old_string,
          newText: editInput.new_string,
        },
      ],
      locations: [{ path: "src/utils/helpers.ts" }],
    },
  },
};

const largeEditOld = `import { useState, useEffect, useCallback } from "react";
import { fetchData, transformData } from "./api";
import { Logger } from "./logger";

const logger = new Logger("DataService");

export class DataService {
  private cache: Map<string, unknown> = new Map();
  private isInitialized = false;

  constructor(private readonly config: ServiceConfig) {
    this.validateConfig();
  }

  private validateConfig(): void {
    if (!this.config.apiKey) {
      throw new Error("API key is required");
    }
    if (!this.config.endpoint) {
      throw new Error("Endpoint is required");
    }
  }

  async initialize(): Promise<void> {
    if (this.isInitialized) return;
    logger.info("Initializing data service...");
    await this.warmupCache();
    this.isInitialized = true;
  }

  private async warmupCache(): Promise<void> {
    const items = await fetchData(this.config.endpoint, "warmup");
    for (const item of items) {
      this.cache.set(item.id, item);
    }
  }

  async fetchItem(id: string): Promise<DataItem | null> {
    if (this.cache.has(id)) {
      return this.cache.get(id) as DataItem;
    }
    const data = await fetchData(this.config.endpoint, id);
    this.cache.set(id, data);
    return data;
  }

  async fetchAll(): Promise<DataItem[]> {
    const items = await fetchData(this.config.endpoint, "all");
    return items;
  }

  clearCache(): void {
    this.cache.clear();
  }

  getCacheSize(): number {
    return this.cache.size;
  }
}`;

const largeEditNew = `import { useState, useEffect, useCallback, useMemo } from "react";
import { fetchData, transformData, batchFetch } from "./api";
import { Logger } from "./logger";

const logger = new Logger("DataService");

export class DataService {
  private cache: Map<string, unknown> = new Map();
  private isInitialized = false;

  constructor(private readonly config: ServiceConfig) {
    this.validateConfig();
  }

  private validateConfig(): void {
    if (!this.config.apiKey) {
      throw new Error("API key is required");
    }
    if (!this.config.endpoint) {
      throw new Error("Endpoint is required");
    }
  }

  async initialize(): Promise<void> {
    if (this.isInitialized) return;
    logger.info("Initializing data service...");
    await this.warmupCache();
    this.isInitialized = true;
  }

  private async warmupCache(): Promise<void> {
    const items = await fetchData(this.config.endpoint, "warmup");
    for (const item of items) {
      this.cache.set(item.id, item);
    }
  }

  async fetchItem(id: string): Promise<DataItem | null> {
    if (this.cache.has(id)) {
      return this.cache.get(id) as DataItem;
    }
    const data = await fetchData(this.config.endpoint, id);
    this.cache.set(id, data);
    return data;
  }

  async fetchAll(): Promise<DataItem[]> {
    const items = await fetchData(this.config.endpoint, "all");
    return items;
  }

  async fetchBatch(ids: string[]): Promise<Map<string, DataItem>> {
    const results = new Map<string, DataItem>();
    const fetched = await batchFetch(this.config.endpoint, ids);
    for (const [id, item] of fetched) {
      this.cache.set(id, item);
      results.set(id, item);
    }
    return results;
  }

  clearCache(): void {
    this.cache.clear();
    logger.info("Cache cleared");
  }

  getCacheSize(): number {
    return this.cache.size;
  }
}`;

export const EditFileLarge: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "Edit `src/services/DataService.ts`",
      kind: "edit",
      status: "completed",
      rawInput: {
        file_path: "src/services/DataService.ts",
        old_string: largeEditOld,
        new_string: largeEditNew,
      },
      content: [
        {
          type: "diff",
          path: "src/services/DataService.ts",
          oldText: largeEditOld,
          newText: largeEditNew,
        },
      ],
      locations: [{ path: "src/services/DataService.ts" }],
    },
  },
};

const writeInput = {
  file_path: "src/utils/logger.ts",
  content: `type LogLevel = "debug" | "info" | "warn" | "error";

export function log(level: LogLevel, message: string, data?: unknown): void {
  const timestamp = new Date().toISOString();
  const prefix = \`[\${timestamp}] [\${level.toUpperCase()}]\`;
  console[level](\`\${prefix} \${message}\`, data ?? "");
}

export const logger = {
  debug: (msg: string, data?: unknown) => log("debug", msg, data),
  info: (msg: string, data?: unknown) => log("info", msg, data),
  warn: (msg: string, data?: unknown) => log("warn", msg, data),
  error: (msg: string, data?: unknown) => log("error", msg, data),
};
`,
};

export const CreateNewFile: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "Write src/utils/logger.ts",
      kind: "edit",
      status: "completed",
      rawInput: writeInput,
      content: [
        {
          type: "diff",
          path: "src/utils/logger.ts",
          oldText: null,
          newText: writeInput.content,
        },
      ],
      locations: [{ path: "src/utils/logger.ts" }],
    },
  },
};

export const EditFileLoading: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "Edit `src/utils/helpers.ts`",
      kind: "edit",
      status: "in_progress",
      rawInput: editInput,
      content: [],
      locations: [{ path: "src/utils/helpers.ts" }],
    },
  },
};

export const DeleteFile: Story = {
  args: {
    toolCall: buildToolCallData(
      "Other",
      {},
      {
        title: "Delete src/deprecated/old-utils.ts",
        kind: "delete",
        locations: [{ path: "src/deprecated/old-utils.ts" }],
      },
    ),
  },
};

export const MoveFile: Story = {
  args: {
    toolCall: buildToolCallData(
      "Other",
      {},
      {
        title: "Move src/utils.ts → src/utils/index.ts",
        kind: "move",
        locations: [{ path: "src/utils.ts" }, { path: "src/utils/index.ts" }],
      },
    ),
  },
};

export const SearchGrep: Story = {
  args: {
    toolCall: {
      ...buildToolCallData("Grep", { pattern: "TODO", path: "src/" }),
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: `src/utils/helpers.ts:15: // TODO: Add error handling
src/components/Button.tsx:42: // TODO: Implement hover state
src/services/api.ts:8: // TODO: Add retry logic
src/hooks/useAuth.ts:23: // TODO: Handle token refresh
src/pages/Dashboard.tsx:67: // TODO: Add loading skeleton`,
          },
        },
      ],
    },
  },
};

export const SearchGlob: Story = {
  args: {
    toolCall: {
      ...buildToolCallData("Glob", { pattern: "**/*.test.ts" }),
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: `src/utils/helpers.test.ts
src/components/Button.test.ts
src/services/api.test.ts
src/hooks/useAuth.test.ts`,
          },
        },
      ],
    },
  },
};

export const SearchLoading: Story = {
  args: {
    toolCall: buildToolCallData(
      "Grep",
      { pattern: "import.*react" },
      { status: "in_progress" },
    ),
  },
};

export const ExecuteCommand: Story = {
  args: {
    toolCall: {
      ...buildToolCallData("Bash", {
        command: "pnpm test",
        description: "Run tests",
      }),
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: `> posthog-code@1.0.0 test
> vitest run

 ✓ src/utils/helpers.test.ts (3 tests) 12ms
 ✓ src/components/Button.test.ts (5 tests) 45ms
 ✓ src/services/api.test.ts (8 tests) 89ms

 Test Files  3 passed (3)
      Tests  16 passed (16)
   Start at  14:23:45
   Duration  1.23s`,
          },
        },
      ],
    },
  },
};

export const ExecuteCommandLoading: Story = {
  args: {
    toolCall: buildToolCallData(
      "Bash",
      { command: "pnpm build", description: "Build project" },
      { status: "in_progress" },
    ),
  },
};

export const ExecuteCommandLongOutput: Story = {
  args: {
    toolCall: {
      ...buildToolCallData("Bash", {
        command: "ls -la node_modules",
        description: "List node_modules",
      }),
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: Array.from(
              { length: 50 },
              (_, i) =>
                `drwxr-xr-x  12 user  staff  384 Jan  1 12:00 package-${i}`,
            ).join("\n"),
          },
        },
      ],
    },
  },
};

export const ExecuteCommandLongInput: Story = {
  args: {
    toolCall: {
      ...buildToolCallData("Bash", {
        command:
          "find /Users/jonathan/dev/posthog-code -type f -name '*.ts' -not -path '*/node_modules/*' -not -path '*/dist/*' | xargs grep -l 'import.*from.*@agentclientprotocol' | head -50",
        description: "Find files importing ACP SDK",
      }),
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: `apps/code/src/renderer/components/permissions/types.ts
apps/code/src/renderer/features/sessions/types.ts
apps/code/src/renderer/features/sessions/components/ConversationView.tsx
packages/agent/src/adapters/claude/conversion/tool-use-to-acp.ts`,
          },
        },
      ],
    },
  },
};

export const ThinkTask: Story = {
  args: {
    toolCall: {
      ...buildToolCallData("Task", {
        description: "Analyze codebase architecture",
        prompt: "Explore the codebase structure and identify key patterns",
      }),
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: `The codebase follows a monorepo structure with pnpm workspaces:

1. apps/code - Main Electron desktop app
2. apps/cli - Command line interface
3. packages/agent - Agent framework
4. packages/core - Shared business logic

Key patterns identified:
- Dependency injection with InversifyJS
- tRPC for type-safe IPC
- Zustand for state management
- Feature-based folder structure`,
          },
        },
      ],
    },
  },
};

export const ThinkTaskLoading: Story = {
  args: {
    toolCall: buildToolCallData(
      "Task",
      { description: "Exploring codebase", prompt: "..." },
      { status: "in_progress" },
    ),
  },
};

export const FetchUrl: Story = {
  args: {
    toolCall: {
      ...buildToolCallData("WebFetch", {
        url: "https://api.example.com/docs/authentication",
        prompt: "Extract authentication requirements",
      }),
      content: [
        {
          type: "content",
          content: {
            type: "resource_link",
            uri: "https://api.example.com/docs/authentication",
            name: "Authentication Docs",
            description: "Extract authentication requirements",
          },
        },
        {
          type: "content",
          content: {
            type: "text",
            text: `# Authentication

The API uses Bearer token authentication.

## Getting a Token

POST /auth/token
Content-Type: application/json

{
  "client_id": "your-client-id",
  "client_secret": "your-client-secret"
}

## Using the Token

Include the token in the Authorization header:

Authorization: Bearer <your-token>`,
          },
        },
      ],
    },
  },
};

export const FetchUrlLoading: Story = {
  args: {
    toolCall: buildToolCallData(
      "WebFetch",
      { url: "https://example.com/api/docs", prompt: "Get API docs" },
      { status: "in_progress" },
    ),
  },
};

export const WebSearch: Story = {
  args: {
    toolCall: {
      ...buildToolCallData("WebSearch", {
        query: "react hooks best practices 2024",
      }),
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: `Found 5 results:

1. React Hooks Best Practices - React Blog
   https://react.dev/learn/hooks-best-practices

2. Top 10 React Hook Patterns - Dev.to
   https://dev.to/hooks-patterns

3. Custom Hooks Guide - Kent C. Dodds
   https://kentcdodds.com/custom-hooks`,
          },
        },
      ],
    },
  },
};

export const QuestionAnswered: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "Which testing framework do you prefer?",
      kind: "question",
      status: "completed",
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: "Vitest - Fast, Vite-native testing framework",
          },
        },
      ],
    },
  },
};

export const QuestionPending: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "Which testing framework do you prefer?",
      kind: "question",
      status: "pending",
      content: [],
    },
  },
};

const planText = `# Add Dark Mode Support

## Overview
Add dark mode toggle to PostHog app with theme persistence.

## Implementation Steps
- Create \`useThemeStore\` Zustand store with theme state
- Add theme toggle button to settings panel
- Update Radix UI Theme component to accept appearance prop
- Add CSS variables for dark mode colors
- Test theme switching persists across restarts`;

export const PlanApproved: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "Ready to code?",
      kind: "switch_mode",
      status: "completed",
      rawInput: { plan: planText },
      content: [
        {
          type: "content",
          content: { type: "text", text: planText },
        },
      ],
    },
  },
};

export const PlanCancelled: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "Ready to code?",
      kind: "switch_mode",
      status: "pending",
      rawInput: { plan: planText },
      content: [
        {
          type: "content",
          content: { type: "text", text: planText },
        },
      ],
    },
    turnCancelled: true,
  },
};

export const UnknownTool: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "CustomTool",
      kind: "other",
      status: "completed",
      content: [],
    },
  },
};

export const UnknownToolLoading: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "CustomTool",
      kind: "other",
      status: "in_progress",
      content: [],
    },
  },
};
