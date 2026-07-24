import type { SessionUpdate } from "@agentclientprotocol/sdk";
import {
  toolInfoFromToolUse,
  toolUpdateFromToolResult,
} from "@posthog/agent/adapters/claude/conversion/tool-use-to-acp";
import type { AcpMessage } from "@posthog/shared/session-events";
import { ConversationView } from "@posthog/ui/features/sessions/components/ConversationView";
import type { Meta, StoryObj } from "@storybook/react-vite";

let timestamp = Date.now();
let messageId = 1;
let toolCallCounter = 1;

function resetCounters() {
  timestamp = Date.now();
  messageId = 1;
  toolCallCounter = 1;
}

function ts(): number {
  timestamp += 100;
  return timestamp;
}

function promptRequest(content: string): AcpMessage {
  const id = messageId++;
  return {
    type: "acp_message",
    ts: ts(),
    message: {
      jsonrpc: "2.0",
      id,
      method: "session/prompt",
      params: { prompt: [{ type: "text", text: content }] },
    },
  };
}

function promptResponse(id: number): AcpMessage {
  return {
    type: "acp_message",
    ts: ts(),
    message: {
      jsonrpc: "2.0",
      id,
      result: { stopReason: "end_turn" },
    },
  };
}

function sessionUpdate(update: SessionUpdate): AcpMessage {
  return {
    type: "acp_message",
    ts: ts(),
    message: {
      method: "session/update",
      params: { update },
    },
  };
}

function agentMessage(text: string): AcpMessage {
  return sessionUpdate({
    sessionUpdate: "agent_message_chunk",
    content: { type: "text", text },
  });
}

interface ToolCallOptions {
  status?: "pending" | "in_progress" | "completed" | "failed";
  result?: { content: unknown; is_error?: boolean };
  cachedFileContent?: Record<string, string>;
}

function toolCall(
  toolName: string,
  toolInput: Record<string, unknown>,
  options: ToolCallOptions = {},
): AcpMessage {
  const { status = "completed", result, cachedFileContent = {} } = options;
  const toolCallId = `tool-${toolCallCounter++}`;

  const info = toolInfoFromToolUse(
    { name: toolName, input: toolInput },
    cachedFileContent,
  );

  let content = info.content;
  if (result && status === "completed") {
    const update = toolUpdateFromToolResult(
      { tool_use_id: toolCallId, ...result } as Parameters<
        typeof toolUpdateFromToolResult
      >[0],
      { name: toolName, input: toolInput },
    );
    if (update.content) {
      content = [...(content || []), ...update.content];
    }
  }

  return sessionUpdate({
    sessionUpdate: "tool_call",
    toolCallId,
    title: info.title,
    kind: info.kind,
    status,
    content,
    locations: info.locations,
    rawInput: toolInput,
  } as SessionUpdate);
}

function buildAllToolCallsConversation(): AcpMessage[] {
  resetCounters();
  const events: AcpMessage[] = [];

  events.push(promptRequest("Help me understand this codebase"));
  events.push(
    agentMessage(
      "I'll explore the codebase to understand its structure. Let me start by reading some key files.\n\n",
    ),
  );

  events.push(
    toolCall(
      "Read",
      { file_path: "/Users/jonathan/dev/posthog-code/package.json" },
      {
        result: {
          content: [
            {
              type: "text",
              text: `{
  "name": "posthog-code",
  "version": "1.0.0",
  "private": true,
  "workspaces": ["apps/*", "packages/*"],
  "scripts": {
    "dev": "turbo dev",
    "build": "turbo build",
    "test": "turbo test",
    "lint": "biome check --write"
  }
}`,
            },
          ],
        },
      },
    ),
  );

  events.push(
    toolCall(
      "Grep",
      { pattern: "export function", path: "src/" },
      {
        result: {
          content: [
            {
              type: "text",
              text: `src/utils/helpers.ts:5: export function formatDate(date: Date): string {
src/utils/helpers.ts:9: export function capitalize(str: string): string {
src/utils/helpers.ts:13: export function debounce<T>(fn: T, delay: number): T {
src/components/Button.tsx:8: export function Button({ children, onClick }: ButtonProps) {
src/hooks/useAuth.ts:12: export function useAuth() {`,
            },
          ],
        },
      },
    ),
  );

  events.push(
    agentMessage(
      "Found some utility functions. Let me make an edit to improve the implementation.\n\n",
    ),
  );

  const oldFileContent = `export function formatDate(date: Date): string {
  return date.toISOString().split("T")[0];
}

export function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}`;

  events.push(
    toolCall(
      "Edit",
      {
        file_path: "src/utils/helpers.ts",
        old_string: `export function formatDate(date: Date): string {
  return date.toISOString().split("T")[0];
}`,
        new_string: `export function formatDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return \`\${year}-\${month}-\${day}\`;
}`,
      },
      {
        cachedFileContent: { "src/utils/helpers.ts": oldFileContent },
      },
    ),
  );

  events.push(
    agentMessage("Now let me run the tests to make sure everything works.\n\n"),
  );

  events.push(
    toolCall(
      "Bash",
      { command: "pnpm test", description: "Run tests" },
      {
        result: {
          content: [
            {
              type: "text",
              text: `> posthog-code@1.0.0 test
> vitest run

 ✓ src/utils/helpers.test.ts (3 tests) 12ms
 ✓ src/components/Button.test.ts (5 tests) 45ms
 ✓ src/hooks/useAuth.test.ts (4 tests) 23ms

 Test Files  3 passed (3)
      Tests  12 passed (12)
   Start at  14:23:45
   Duration  892ms`,
            },
          ],
        },
      },
    ),
  );

  events.push(
    agentMessage("Tests pass! Let me also check the API documentation.\n\n"),
  );

  events.push(
    toolCall(
      "WebFetch",
      {
        url: "https://api.example.com/docs",
        prompt: "Get API documentation for reference",
      },
      {
        result: {
          content: [
            {
              type: "text",
              text: `# API Documentation

## Authentication
All endpoints require Bearer token authentication.

## Endpoints
- GET /users - List all users
- POST /users - Create a new user
- GET /users/:id - Get user by ID`,
            },
          ],
        },
      },
    ),
  );

  events.push(
    agentMessage(
      "Let me think about the best approach to implement the new feature...\n\n",
    ),
  );

  events.push(
    toolCall(
      "Task",
      {
        description: "Analyze codebase architecture",
        prompt:
          "Explore the codebase structure and identify patterns for adding new features",
      },
      {
        result: {
          content: [
            {
              type: "text",
              text: `Based on my analysis:

1. The codebase follows a monorepo structure
2. Uses TypeScript with strict mode
3. Has good test coverage
4. Follows feature-based folder organization

Recommendation: Add the new feature in a dedicated feature folder with its own components, hooks, and tests.`,
            },
          ],
        },
      },
    ),
  );

  events.push(agentMessage("Now creating a new file for the feature.\n\n"));

  events.push(
    toolCall("Write", {
      file_path: "src/features/analytics/index.ts",
      content: `export interface AnalyticsEvent {
  name: string;
  properties?: Record<string, unknown>;
  timestamp: Date;
}

export function trackEvent(event: AnalyticsEvent): void {
  console.log("[Analytics]", event.name, event.properties);
}

export function useAnalytics() {
  return {
    track: (name: string, properties?: Record<string, unknown>) => {
      trackEvent({ name, properties, timestamp: new Date() });
    },
  };
}
`,
    }),
  );

  events.push(
    agentMessage(
      "I've created the analytics module. The codebase is well-structured with:\n\n- **Monorepo setup** using pnpm workspaces\n- **TypeScript** with strict type checking\n- **Feature-based architecture** for scalability\n- **Good test coverage** across all packages\n\nLet me know if you'd like me to explain any specific part in more detail!",
    ),
  );

  events.push(promptResponse(1));

  events.push(promptRequest("Search the web for React best practices"));

  events.push(
    agentMessage("I'll search for the latest React best practices.\n\n"),
  );

  events.push(
    toolCall(
      "WebSearch",
      { query: "React hooks best practices 2024" },
      {
        result: {
          content: [
            {
              type: "text",
              text: `Found 5 results:

1. React Hooks Best Practices - React Blog
   https://react.dev/learn/hooks-best-practices

2. Top 10 React Hook Patterns - Dev.to
   https://dev.to/hooks-patterns

3. Custom Hooks Guide - Kent C. Dodds
   https://kentcdodds.com/custom-hooks`,
            },
          ],
        },
      },
    ),
  );

  events.push(
    agentMessage(
      "Here are some great resources on React best practices. The key points are:\n\n1. Keep hooks at the top level\n2. Use custom hooks for reusable logic\n3. Memoize expensive computations",
    ),
  );

  events.push(promptResponse(2));

  events.push(promptRequest("Find all TypeScript files in the project"));

  events.push(agentMessage("I'll search for all TypeScript files.\n\n"));

  events.push(
    toolCall(
      "Glob",
      { pattern: "**/*.ts", path: "src/" },
      {
        result: {
          content: [
            {
              type: "text",
              text: `src/index.ts
src/utils/helpers.ts
src/utils/logger.ts
src/components/Button.ts
src/hooks/useAuth.ts
src/features/analytics/index.ts`,
            },
          ],
        },
      },
    ),
  );

  events.push(agentMessage("Found 6 TypeScript files in the src directory."));

  events.push(promptResponse(3));

  return events;
}

const meta: Meta<typeof ConversationView> = {
  title: "Features/Sessions/ConversationView",
  component: ConversationView,
  parameters: {
    layout: "fullscreen",
  },
  decorators: [
    (Story) => (
      <div className="flex h-[90vh] flex-col">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ConversationView>;

export const AllToolCalls: Story = {
  args: {
    events: buildAllToolCallsConversation(),
    isPromptPending: false,
    repoPath: "/Users/jonathan/dev/posthog-code",
  },
};

export const WithPendingPrompt: Story = {
  args: {
    events: (() => {
      const events = buildAllToolCallsConversation();
      events.push(promptRequest("What else can you help me with?"));
      events.push(
        agentMessage(
          "I can help you with many things! Let me search for...\n\n",
        ),
      );
      events.push(
        toolCall("Grep", { pattern: "TODO" }, { status: "in_progress" }),
      );
      return events;
    })(),
    isPromptPending: true,
    promptStartedAt: Date.now() - 5000,
    repoPath: "/Users/jonathan/dev/posthog-code",
  },
};

export const Empty: Story = {
  args: {
    events: [],
    isPromptPending: false,
  },
};

export const SingleTurn: Story = {
  args: {
    events: (() => {
      resetCounters();
      const events: AcpMessage[] = [];

      events.push(promptRequest("Hello!"));
      events.push(
        agentMessage(
          "Hello! I'm ready to help you with your codebase. What would you like to do?",
        ),
      );
      events.push(promptResponse(1));

      return events;
    })(),
    isPromptPending: false,
  },
};

export const LongConversation: Story = {
  args: {
    events: (() => {
      resetCounters();
      const events: AcpMessage[] = [];

      for (let i = 0; i < 10; i++) {
        events.push(
          promptRequest(`Question ${i + 1}: How does feature ${i + 1} work?`),
        );
        events.push(
          agentMessage(
            `Feature ${i + 1} works by using a combination of React hooks and context providers. Here's a brief overview:\n\n`,
          ),
        );
        events.push(
          toolCall(
            "Read",
            { file_path: `src/features/feature${i + 1}/index.ts` },
            {
              result: {
                content: [
                  {
                    type: "text",
                    text: `export function useFeature${i + 1}() {
  const [state, setState] = useState(null);

  useEffect(() => {
    loadFeature${i + 1}Data().then(setState);
  }, []);

  return { state, refresh: () => loadFeature${i + 1}Data().then(setState) };
}`,
                  },
                ],
              },
            },
          ),
        );
        events.push(
          agentMessage(
            `The feature uses a custom hook pattern with useState and useEffect for data loading. Would you like me to explain more?\n\n`,
          ),
        );
        events.push(promptResponse(i + 1));
      }

      return events;
    })(),
    isPromptPending: false,
    repoPath: "/Users/jonathan/dev/posthog-code",
  },
};

function buildMarkdownShowcaseConversation(): AcpMessage[] {
  resetCounters();
  const events: AcpMessage[] = [];

  events.push(promptRequest("Show me all markdown rendering capabilities"));

  events.push(
    agentMessage(`# API Reference: Authentication Service v2.4.1

## Quick Start

Import and initialize the client:

\`\`\`typescript
import { AuthClient } from '@acme/auth-sdk';

const client = new AuthClient({
  apiKey: process.env.AUTH_API_KEY,
  timeout: 30000,
  retries: 3
});

const session = await client.authenticate({
  email: 'user@example.com',
  password: '••••••••'
});
\`\`\`

## Rate Limits

| Tier | Requests/min | Burst | Price |
|------|-------------|-------|-------|
| Free | 60 | 100 | $0 |
| Pro | 1,000 | 2,500 | $29/mo |
| Enterprise | 10,000 | 50k | Custom |

## Error Handling

When authentication fails, you'll receive an error response:

\`\`\`json
{
  "error": {
    "code": "AUTH_INVALID_CREDENTIALS",
    "message": "The provided credentials are invalid.",
    "requestId": "req_7xKo2nhV03",
    "timestamp": "2024-01-15T09:23:41.892Z"
  }
}
\`\`\`

Common error codes:

- \`AUTH_INVALID_CREDENTIALS\` — Wrong email or password
- \`AUTH_RATE_LIMITED\` — Too many requests (wait 60s)
- \`AUTH_TOKEN_EXPIRED\` — Refresh token or re-authenticate
- \`AUTH_MFA_REQUIRED\` — 2FA verification needed

## Terminal Output

\`\`\`bash
$ npm run build
> @acme/dashboard@3.2.0 build
> next build

▲ Next.js 14.1.0

Creating an optimized production build...
✓ Compiled successfully in 12.4s
✓ Linting and checking validity
✓ Collecting page data
✓ Generating static pages (24/24)
✓ Finalizing page optimization

Route (app)                Size     First Load JS
┌ ○ /                      5.2 kB   89.1 kB
├ ○ /dashboard            12.8 kB   96.7 kB
├ ● /settings/[...slug]    3.1 kB   87.0 kB
└ ○ /api/health            0 B      0 B

○  (Static)  prerendered as static content
●  (SSG)     prerendered as static HTML
\`\`\`

## Configuration

Create a \`config.yaml\` in your project root:

\`\`\`yaml
auth:
  provider: oauth2
  issuer: https://auth.acme.dev
  client_id: \${CLIENT_ID}
  scopes:
    - openid
    - profile
    - email

database:
  host: localhost
  port: 5432
  pool_size: 20
  ssl: true

logging:
  level: info  # debug | info | warn | error
  format: json
\`\`\`

## Metrics & Observability

Average response times (p50 / p95 / p99):

- **POST /auth/token** — 45ms / 120ms / 340ms
- **GET /auth/userinfo** — 12ms / 28ms / 65ms
- **POST /auth/refresh** — 38ms / 95ms / 210ms

Memory usage: ~128MB baseline, scales to 512MB under load.

---

## Text Formatting

This section demonstrates various **text formatting** options available:

- **Bold text** for emphasis
- *Italic text* for subtle emphasis
- ~~Strikethrough~~ for deleted content
- \`inline code\` for technical terms
- Combined ***bold and italic*** together

> **Note:** This is a blockquote with important information. Use blockquotes to highlight key points or warnings in your documentation.

### Task Lists

- [x] Implement authentication flow
- [x] Add rate limiting
- [ ] Write integration tests
- [ ] Update API documentation

### Nested Lists

1. First level item
   - Second level bullet
   - Another bullet
     1. Third level numbered
     2. Another numbered
2. Back to first level
   - With a bullet point

### Links and References

Check out the [official documentation](https://docs.example.com) for more details.

For keyboard shortcuts, use <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>P</kbd> to open the command palette.

---

## Changelog

**v2.4.1** (2024-01-12)
- Fixed race condition in token refresh logic (#1847)
- Improved error messages for SAML configurations

**v2.4.0** (2024-01-08)
- Added support for passkeys/WebAuthn
- New \`onSessionExpired\` callback hook
- **Breaking:** Removed deprecated \`legacyMode\` option

*Last updated: January 15, 2024 • Found an issue? [Open a PR](https://github.com/acme/auth-sdk)*`),
  );

  events.push(promptResponse(1));

  return events;
}

export const MarkdownShowcase: Story = {
  args: {
    events: buildMarkdownShowcaseConversation(),
    isPromptPending: false,
    repoPath: "/Users/jonathan/dev/posthog-code",
  },
};

function buildMarkdownDebugConversation(): AcpMessage[] {
  resetCounters();
  const events: AcpMessage[] = [];

  events.push(promptRequest("Show me all markdown features"));

  events.push(
    agentMessage(`# Heading 1
## Heading 2
### Heading 3
#### Heading 4
##### Heading 5
###### Heading 6

---

## Text Formatting

Regular paragraph text.

**Bold text**

*Italic text*

***Bold and italic***

~~Strikethrough~~

---

## Inline Code

Use \`const x = 1\` for inline code.

Error codes: \`AUTH_INVALID\`, \`RATE_LIMITED\`, \`NOT_FOUND\`

---

## Code Blocks

\`\`\`typescript
interface User {
  id: string;
  name: string;
  email: string;
}

function getUser(id: string): User {
  return { id, name: "John", email: "john@example.com" };
}
\`\`\`

\`\`\`json
{
  "name": "example",
  "version": "1.0.0",
  "dependencies": {
    "react": "^18.0.0"
  }
}
\`\`\`

\`\`\`bash
$ npm install
$ npm run build
$ npm test
\`\`\`

\`\`\`yaml
config:
  enabled: true
  options:
    - first
    - second
\`\`\`

---

## Blockquotes

> This is a blockquote.

> **Note:** Important information here.

> Multi-line blockquote
> continues on next line.

---

## Unordered Lists

- Item one
- Item two
- Item three

* Also works with asterisks
* Another item

---

## Ordered Lists

1. First item
2. Second item
3. Third item

---

## Nested Lists

- Parent item
  - Child item
  - Another child
    - Grandchild
- Back to parent
  1. Numbered child
  2. Another numbered

1. Numbered parent
   - Bullet child
   - Another bullet
2. Second numbered parent

---

## Task Lists

- [x] Completed task
- [x] Another completed
- [ ] Incomplete task
- [ ] Another incomplete

---

## Links

[Simple link](https://example.com)

[Link with title](https://example.com "Example Site")

Check the [documentation](https://docs.example.com) for more info.

---

## Tables

| Header 1 | Header 2 | Header 3 |
|----------|----------|----------|
| Cell 1   | Cell 2   | Cell 3   |
| Cell 4   | Cell 5   | Cell 6   |

| Left | Center | Right |
|:-----|:------:|------:|
| L    | C      | R     |
| L    | C      | R     |

---

## Horizontal Rules

Above the rule

---

Below the rule

***

Another separator

___

Final separator

---

## Mixed Content

Here's a paragraph with **bold**, *italic*, \`code\`, and a [link](https://example.com).

1. List with **bold item**
2. List with *italic item*
3. List with \`code item\`
4. List with [link item](https://example.com)

> Blockquote with **bold**, *italic*, and \`code\`.

---

## Edge Cases

**Bold at start** of paragraph.

Paragraph ending with **bold**

*Italic at start* of paragraph.

Paragraph ending with *italic*

\`Code at start\` of paragraph.

Paragraph ending with \`code\`

Empty paragraph below:

Next paragraph after empty.`),
  );

  events.push(promptResponse(1));

  return events;
}

export const MarkdownDebug: Story = {
  args: {
    events: buildMarkdownDebugConversation(),
    isPromptPending: false,
    repoPath: "/Users/jonathan/dev/posthog-code",
  },
};
