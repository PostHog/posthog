import { toolInfoFromToolUse } from "@posthog/agent/adapters/claude/conversion/tool-use-to-acp";
import {
  buildExitPlanModePermissionOptions,
  buildPermissionOptions,
} from "@posthog/agent/adapters/claude/permissions/permission-options";
import {
  buildQuestionOptions,
  buildQuestionToolCallData,
  type QuestionItem,
} from "@posthog/agent/adapters/claude/questions/utils";
import { PermissionSelector } from "@posthog/ui/features/permissions/PermissionSelector";
import type { Meta, StoryObj } from "@storybook/react-vite";

function buildToolCallData(
  toolName: string,
  toolInput: Record<string, unknown>,
) {
  return {
    toolCallId: `story-${Date.now()}`,
    ...toolInfoFromToolUse({ name: toolName, input: toolInput }, {}),
  };
}

const meta: Meta<typeof PermissionSelector> = {
  title: "Components/Permissions/PermissionSelector",
  component: PermissionSelector,
  parameters: {
    layout: "padded",
  },
  argTypes: {
    onSelect: { action: "selected" },
    onCancel: { action: "cancelled" },
  },
};

export default meta;
type Story = StoryObj<typeof PermissionSelector>;

const CWD = "/Users/jonathan/dev/posthog-code";

const bashInput = { command: "pnpm add -D vitest" };
export const Execute: Story = {
  args: {
    toolCall: buildToolCallData("Bash", bashInput),
    options: buildPermissionOptions("Bash", bashInput, CWD),
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
export const Edit: Story = {
  args: {
    toolCall: buildToolCallData("Edit", editInput),
    options: buildPermissionOptions("Edit", editInput),
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
    toolCall: buildToolCallData("Write", writeInput),
    options: buildPermissionOptions("Write", writeInput),
  },
};

const largeEditInput = {
  file_path: "src/services/api-client.ts",
  old_string: `import { HttpClient } from "./http";
import { Config } from "../config";

export class ApiClient {
  private client: HttpClient;
  private baseUrl: string;

  constructor(config: Config) {
    this.client = new HttpClient();
    this.baseUrl = config.apiUrl;
  }

  async get<T>(path: string): Promise<T> {
    return this.client.get(\`\${this.baseUrl}\${path}\`);
  }

  async post<T>(path: string, data: unknown): Promise<T> {
    return this.client.post(\`\${this.baseUrl}\${path}\`, data);
  }

  async put<T>(path: string, data: unknown): Promise<T> {
    return this.client.put(\`\${this.baseUrl}\${path}\`, data);
  }

  async delete(path: string): Promise<void> {
    return this.client.delete(\`\${this.baseUrl}\${path}\`);
  }
}`,
  new_string: `import { HttpClient, RequestOptions, RetryConfig } from "./http";
import { Config } from "../config";
import { Logger } from "../utils/logger";

export interface ApiClientOptions {
  timeout?: number;
  retries?: number;
  retryDelay?: number;
}

const DEFAULT_OPTIONS: ApiClientOptions = {
  timeout: 30000,
  retries: 3,
  retryDelay: 1000,
};

export class ApiClient {
  private client: HttpClient;
  private baseUrl: string;
  private logger: Logger;
  private options: ApiClientOptions;

  constructor(config: Config, options: ApiClientOptions = {}) {
    this.client = new HttpClient();
    this.baseUrl = config.apiUrl;
    this.logger = new Logger("ApiClient");
    this.options = { ...DEFAULT_OPTIONS, ...options };
  }

  private getRequestOptions(): RequestOptions {
    return {
      timeout: this.options.timeout,
      headers: {
        "Content-Type": "application/json",
        "X-Request-Id": crypto.randomUUID(),
      },
    };
  }

  private getRetryConfig(): RetryConfig {
    return {
      maxRetries: this.options.retries ?? 3,
      delay: this.options.retryDelay ?? 1000,
      shouldRetry: (error: Error) => {
        return error.message.includes("ETIMEDOUT") ||
               error.message.includes("ECONNRESET");
      },
    };
  }

  async get<T>(path: string): Promise<T> {
    this.logger.debug(\`GET \${path}\`);
    const response = await this.client.get<T>(
      \`\${this.baseUrl}\${path}\`,
      this.getRequestOptions(),
      this.getRetryConfig()
    );
    this.logger.debug(\`GET \${path} completed\`);
    return response;
  }

  async post<T>(path: string, data: unknown): Promise<T> {
    this.logger.debug(\`POST \${path}\`, { data });
    const response = await this.client.post<T>(
      \`\${this.baseUrl}\${path}\`,
      data,
      this.getRequestOptions(),
      this.getRetryConfig()
    );
    this.logger.debug(\`POST \${path} completed\`);
    return response;
  }

  async put<T>(path: string, data: unknown): Promise<T> {
    this.logger.debug(\`PUT \${path}\`, { data });
    const response = await this.client.put<T>(
      \`\${this.baseUrl}\${path}\`,
      data,
      this.getRequestOptions(),
      this.getRetryConfig()
    );
    this.logger.debug(\`PUT \${path} completed\`);
    return response;
  }

  async patch<T>(path: string, data: unknown): Promise<T> {
    this.logger.debug(\`PATCH \${path}\`, { data });
    const response = await this.client.patch<T>(
      \`\${this.baseUrl}\${path}\`,
      data,
      this.getRequestOptions(),
      this.getRetryConfig()
    );
    this.logger.debug(\`PATCH \${path} completed\`);
    return response;
  }

  async delete(path: string): Promise<void> {
    this.logger.debug(\`DELETE \${path}\`);
    await this.client.delete(
      \`\${this.baseUrl}\${path}\`,
      this.getRequestOptions(),
      this.getRetryConfig()
    );
    this.logger.debug(\`DELETE \${path} completed\`);
  }
}`,
};
export const LargeEdit: Story = {
  args: {
    toolCall: buildToolCallData("Edit", largeEditInput),
    options: buildPermissionOptions("Edit", largeEditInput),
  },
};

const largeWriteInput = {
  file_path: "src/components/DataTable.tsx",
  content: `import React, { useState, useMemo, useCallback } from "react";
import { Table, Thead, Tbody, Tr, Th, Td } from "./Table";
import { Pagination } from "./Pagination";
import { SearchInput } from "./SearchInput";
import { SortIcon } from "./icons/SortIcon";

export interface Column<T> {
  key: keyof T;
  label: string;
  sortable?: boolean;
  render?: (value: T[keyof T], row: T) => React.ReactNode;
  width?: string | number;
}

export interface DataTableProps<T extends Record<string, unknown>> {
  data: T[];
  columns: Column<T>[];
  pageSize?: number;
  searchable?: boolean;
  searchPlaceholder?: string;
  emptyMessage?: string;
  loading?: boolean;
  onRowClick?: (row: T) => void;
}

type SortDirection = "asc" | "desc" | null;

interface SortState<T> {
  column: keyof T | null;
  direction: SortDirection;
}

export function DataTable<T extends Record<string, unknown>>({
  data,
  columns,
  pageSize = 10,
  searchable = false,
  searchPlaceholder = "Search...",
  emptyMessage = "No data available",
  loading = false,
  onRowClick,
}: DataTableProps<T>) {
  const [currentPage, setCurrentPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortState, setSortState] = useState<SortState<T>>({
    column: null,
    direction: null,
  });

  const filteredData = useMemo(() => {
    if (!searchQuery) return data;

    const query = searchQuery.toLowerCase();
    return data.filter((row) =>
      columns.some((col) => {
        const value = row[col.key];
        if (value == null) return false;
        return String(value).toLowerCase().includes(query);
      })
    );
  }, [data, columns, searchQuery]);

  const sortedData = useMemo(() => {
    if (!sortState.column || !sortState.direction) return filteredData;

    return [...filteredData].sort((a, b) => {
      const aVal = a[sortState.column!];
      const bVal = b[sortState.column!];

      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return sortState.direction === "asc" ? 1 : -1;
      if (bVal == null) return sortState.direction === "asc" ? -1 : 1;

      const comparison = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
      return sortState.direction === "asc" ? comparison : -comparison;
    });
  }, [filteredData, sortState]);

  const paginatedData = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return sortedData.slice(start, start + pageSize);
  }, [sortedData, currentPage, pageSize]);

  const totalPages = Math.ceil(sortedData.length / pageSize);

  const handleSort = useCallback((column: keyof T) => {
    setSortState((prev) => {
      if (prev.column !== column) {
        return { column, direction: "asc" };
      }
      if (prev.direction === "asc") {
        return { column, direction: "desc" };
      }
      return { column: null, direction: null };
    });
  }, []);

  const handleSearch = useCallback((value: string) => {
    setSearchQuery(value);
    setCurrentPage(1);
  }, []);

  if (loading) {
    return (
      <div className="data-table-loading">
        <span>Loading...</span>
      </div>
    );
  }

  return (
    <div className="data-table">
      {searchable && (
        <div className="data-table-search">
          <SearchInput
            value={searchQuery}
            onChange={handleSearch}
            placeholder={searchPlaceholder}
          />
        </div>
      )}

      <Table>
        <Thead>
          <Tr>
            {columns.map((col) => (
              <Th
                key={String(col.key)}
                style={{ width: col.width }}
                onClick={col.sortable ? () => handleSort(col.key) : undefined}
                className={col.sortable ? "sortable" : ""}
              >
                {col.label}
                {col.sortable && (
                  <SortIcon
                    direction={
                      sortState.column === col.key ? sortState.direction : null
                    }
                  />
                )}
              </Th>
            ))}
          </Tr>
        </Thead>
        <Tbody>
          {paginatedData.length === 0 ? (
            <Tr>
              <Td colSpan={columns.length} className="empty-message">
                {emptyMessage}
              </Td>
            </Tr>
          ) : (
            paginatedData.map((row, index) => (
              <Tr
                key={index}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={onRowClick ? "clickable" : ""}
              >
                {columns.map((col) => (
                  <Td key={String(col.key)}>
                    {col.render
                      ? col.render(row[col.key], row)
                      : String(row[col.key] ?? "")}
                  </Td>
                ))}
              </Tr>
            ))
          )}
        </Tbody>
      </Table>

      {totalPages > 1 && (
        <Pagination
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={setCurrentPage}
        />
      )}
    </div>
  );
}
`,
};
export const LargeNewFile: Story = {
  args: {
    toolCall: buildToolCallData("Write", largeWriteInput),
    options: buildPermissionOptions("Write", largeWriteInput),
  },
};

const readInput = { file_path: "/Users/jonathan/dev/posthog-code/.env" };
export const Read: Story = {
  args: {
    toolCall: buildToolCallData("Read", readInput),
    options: buildPermissionOptions("Read", readInput),
  },
};

const fetchInput = {
  url: "https://api.example.com/docs/authentication",
  prompt: "Extract the authentication requirements and API key format",
};
export const FetchUrl: Story = {
  args: {
    toolCall: buildToolCallData("WebFetch", fetchInput),
    options: buildPermissionOptions("WebFetch", fetchInput),
  },
};

const searchInput = { query: "react hooks best practices 2024" };
export const WebSearch: Story = {
  args: {
    toolCall: buildToolCallData("WebSearch", searchInput),
    options: buildPermissionOptions("WebSearch", searchInput),
  },
};

const grepInput = { pattern: "TODO" };
export const Search: Story = {
  args: {
    toolCall: buildToolCallData("Grep", grepInput),
    options: buildPermissionOptions("Grep", grepInput),
  },
};

const taskInput = { description: "Analyze codebase architecture" };
export const Think: Story = {
  args: {
    toolCall: buildToolCallData("Task", taskInput),
    options: buildPermissionOptions("Task", taskInput),
  },
};

export const Default: Story = {
  args: {
    toolCall: buildToolCallData("Unknown", {}),
    options: buildPermissionOptions("Unknown", {}),
  },
};

function buildMcpToolCallData(
  mcpToolName: string,
  rawInput: Record<string, unknown>,
) {
  return {
    toolCallId: `story-${Date.now()}`,
    title: mcpToolName.split("__").slice(2).join("__") || mcpToolName,
    kind: "other" as const,
    rawInput,
    content: [],
    _meta: { claudeCode: { toolName: mcpToolName } },
  };
}

const posthogExecInput = {
  command: 'call execute-sql {"query":"select 1"}',
};
export const McpPostHogExec: Story = {
  args: {
    toolCall: buildMcpToolCallData("mcp__posthog__exec", posthogExecInput),
    options: buildPermissionOptions("mcp__posthog__exec", posthogExecInput),
  },
};

const posthogExecInfoInput = { command: "info execute-sql" };
export const McpPostHogExecInfo: Story = {
  args: {
    toolCall: buildMcpToolCallData("mcp__posthog__exec", posthogExecInfoInput),
    options: buildPermissionOptions("mcp__posthog__exec", posthogExecInfoInput),
  },
};

const posthogExecToolsInput = { command: "tools" };
export const McpPostHogExecTools: Story = {
  args: {
    toolCall: buildMcpToolCallData("mcp__posthog__exec", posthogExecToolsInput),
    options: buildPermissionOptions(
      "mcp__posthog__exec",
      posthogExecToolsInput,
    ),
  },
};

const posthogExecSearchInput = { command: "search query-" };
export const McpPostHogExecSearch: Story = {
  args: {
    toolCall: buildMcpToolCallData(
      "mcp__posthog__exec",
      posthogExecSearchInput,
    ),
    options: buildPermissionOptions(
      "mcp__posthog__exec",
      posthogExecSearchInput,
    ),
  },
};

const githubIssueInput = {
  owner: "PostHog",
  repo: "posthog",
  title: "Investigate intermittent flake in foo test",
  body: "Seen on CI runs 12345 and 67890 — appears related to fixture cleanup ordering.",
  labels: ["bug", "ci"],
};
export const McpGithubCreateIssue: Story = {
  args: {
    toolCall: buildMcpToolCallData(
      "mcp__github__create_issue",
      githubIssueInput,
    ),
    options: buildPermissionOptions(
      "mcp__github__create_issue",
      githubIssueInput,
    ),
  },
};

export const McpNoArgs: Story = {
  args: {
    toolCall: buildMcpToolCallData("mcp__example__ping", {}),
    options: buildPermissionOptions("mcp__example__ping", {}),
  },
};

const exitPlanModeInput = {
  plan: `# Add Dark Mode Support

## Overview
Add dark mode toggle to PostHog app with theme persistence.

## Implementation Steps
- Create \`useThemeStore\` Zustand store with theme state (\`light\` | \`dark\` | \`system\`)
- Add theme toggle button to settings panel that cycles through theme options
- Update Radix UI Theme component to accept \`appearance\` prop from store
- Add CSS variables for dark mode colors in global styles
- Test theme switching persists across app restarts

## Critical Files
- \`apps/code/src/renderer/stores/theme-store.ts\` (new)
- \`apps/code/src/renderer/App.tsx\` (modify Theme provider)
- \`apps/code/src/renderer/features/settings/SettingsPanel.tsx\` (add toggle)

## Verification
- Launch app, toggle dark mode, verify colors change
- Restart app, verify theme persists
- Test system theme option follows OS preference`,
};

const largePlanInput = {
  plan: `# Complete Application Refactoring Plan

## Executive Summary
This plan outlines a comprehensive refactoring of the application architecture to improve maintainability, performance, and developer experience. The changes will be implemented in phases to minimize disruption.

## Phase 1: State Management Overhaul

### 1.1 Migrate to New Store Architecture
- Audit all existing Zustand stores for redundant state
- Implement store slicing pattern for better code splitting
- Add middleware for persistence, logging, and devtools
- Create store factory functions for consistent patterns

### 1.2 Normalize Data Structures
- Design normalized schema for entities (users, tasks, sessions)
- Implement selectors with memoization using reselect
- Add entity adapters for CRUD operations
- Create relationship mappings between entities

### 1.3 Implement Optimistic Updates
- Add rollback mechanisms for failed mutations
- Create pending state tracking for UI feedback
- Implement conflict resolution strategies
- Add retry logic with exponential backoff

## Phase 2: API Layer Improvements

### 2.1 Implement Request Caching
- Add SWR-style caching with stale-while-revalidate
- Implement cache invalidation strategies
- Add prefetching for anticipated requests
- Create cache persistence layer

### 2.2 Error Handling Standardization
- Create unified error types and codes
- Implement error boundary components
- Add structured logging for errors
- Create error recovery workflows

### 2.3 Request Batching
- Implement DataLoader pattern for batching
- Add request deduplication
- Create priority queue for requests
- Implement cancellation tokens

## Phase 3: Component Architecture

### 3.1 Component Library Extraction
- Identify reusable components
- Create component documentation with Storybook
- Implement visual regression testing
- Add accessibility testing

### 3.2 Performance Optimization
- Implement code splitting at route level
- Add lazy loading for heavy components
- Optimize bundle size with tree shaking
- Implement virtual scrolling for lists

### 3.3 Testing Infrastructure
- Set up unit testing with Vitest
- Add integration tests with Testing Library
- Implement E2E tests with Playwright
- Create test data factories

## Phase 4: Developer Experience

### 4.1 Tooling Improvements
- Configure ESLint with strict rules
- Add Prettier for formatting
- Implement husky for git hooks
- Add commitlint for commit messages

### 4.2 Documentation
- Create architecture decision records
- Write API documentation
- Add inline code documentation
- Create onboarding guides

### 4.3 CI/CD Pipeline
- Set up automated testing
- Implement deployment previews
- Add performance budgets
- Create release automation

## Critical Files to Modify

### Store Files
- \`src/stores/index.ts\` - Store exports
- \`src/stores/user-store.ts\` - User state
- \`src/stores/task-store.ts\` - Task state
- \`src/stores/session-store.ts\` - Session state
- \`src/stores/middleware/\` - Custom middleware

### API Files
- \`src/api/client.ts\` - API client
- \`src/api/cache.ts\` - Caching layer
- \`src/api/errors.ts\` - Error handling
- \`src/api/hooks/\` - React Query hooks

### Component Files
- \`src/components/ui/\` - Base components
- \`src/components/forms/\` - Form components
- \`src/components/layout/\` - Layout components
- \`src/features/\` - Feature modules

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking changes | High | Feature flags, gradual rollout |
| Performance regression | Medium | Benchmarking, monitoring |
| Developer friction | Low | Documentation, training |
| Data migration | High | Backup, rollback plan |

## Timeline Estimate
- Phase 1: 2-3 weeks
- Phase 2: 2 weeks
- Phase 3: 3-4 weeks
- Phase 4: 1-2 weeks

## Success Metrics
- 50% reduction in bundle size
- 30% improvement in Time to Interactive
- 90% test coverage
- Zero critical bugs in production`,
};
export const ExitPlanMode: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "Approve this plan to proceed?",
      kind: "switch_mode",
      content: [
        {
          type: "content",
          content: { type: "text", text: exitPlanModeInput.plan },
        },
      ],
    },
    options: buildExitPlanModePermissionOptions(),
  },
};

export const ExitPlanModeLarge: Story = {
  args: {
    toolCall: {
      toolCallId: `story-${Date.now()}`,
      title: "Approve this plan to proceed?",
      kind: "switch_mode",
      content: [
        {
          type: "content",
          content: { type: "text", text: largePlanInput.plan },
        },
      ],
    },
    options: buildExitPlanModePermissionOptions(),
  },
};

const singleQuestion: QuestionItem[] = [
  {
    question: "Which testing framework do you prefer?",
    header: "Testing Framework",
    options: [
      { label: "Vitest", description: "Fast, Vite-native" },
      { label: "Jest", description: "Popular, mature" },
      { label: "Mocha", description: "Flexible, configurable" },
    ],
  },
];

export const Question: Story = {
  args: {
    toolCall: buildQuestionToolCallData(singleQuestion),
    options: buildQuestionOptions(singleQuestion[0]),
  },
};

const multiStepQuestions: QuestionItem[] = [
  {
    header: "Framework",
    question: "Which frontend framework do you prefer?",
    options: [
      { label: "React", description: "Component-based UI library" },
      { label: "Vue", description: "Progressive framework" },
      { label: "Svelte", description: "Compiler-based" },
    ],
  },
  {
    header: "Package Manager",
    question: "What is your preferred package manager?",
    options: [
      { label: "pnpm", description: "Fast, disk efficient" },
      { label: "npm", description: "Default Node.js package manager" },
      { label: "yarn", description: "Fast, reliable" },
    ],
  },
  {
    header: "Testing",
    question: "Which testing framework do you use?",
    options: [
      { label: "Vitest", description: "Fast, Vite-native" },
      { label: "Jest", description: "Popular, mature" },
    ],
  },
];

export const QuestionMultiStep: Story = {
  args: {
    toolCall: buildQuestionToolCallData(multiStepQuestions),
    options: buildQuestionOptions(multiStepQuestions[0]),
  },
};

export const QuestionMultiStepSync: Story = {
  args: {
    toolCall: buildQuestionToolCallData(multiStepQuestions),
    options: buildQuestionOptions(multiStepQuestions[0]),
  },
  parameters: {
    docs: {
      description: {
        story:
          "Regression: advancing steps should update the question text and options for each step.",
      },
    },
  },
};

const multiSelectQuestion: QuestionItem[] = [
  {
    question: "Which features do you want to enable?",
    header: "Features",
    options: [
      { label: "Dark mode", description: "Enable dark theme" },
      { label: "Notifications", description: "Push notifications" },
      { label: "Analytics", description: "Usage tracking" },
      { label: "Auto-save", description: "Save changes automatically" },
    ],
    multiSelect: true,
  },
];

export const QuestionMultiSelect: Story = {
  args: {
    toolCall: buildQuestionToolCallData(multiSelectQuestion),
    options: buildQuestionOptions(multiSelectQuestion[0]),
  },
};
