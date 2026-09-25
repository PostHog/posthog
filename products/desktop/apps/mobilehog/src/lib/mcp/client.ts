import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type {
  CallToolResult,
  ReadResourceResult,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { MCP_HOSTS } from "@/config";
import { requireSession } from "@/lib/auth";

// The sandbox wrapper sends this too; it is what makes exec results carry the
// UI-app resource URI and structured data instead of plain text.
const CONSUMER = "posthog-code";

let connection: { key: string; client: Promise<Client> } | null = null;

// One MCP client to the PostHog server for the signed-in host, opened lazily
// and reopened if the session changes.
function getClient(): Promise<Client> {
  const session = requireSession();
  const key = `${session.host}|${session.apiKey}`;
  if (connection?.key === key) return connection.client;
  const url = new URL(MCP_HOSTS[session.region]);
  const transport = new StreamableHTTPClientTransport(url, {
    requestInit: {
      headers: {
        Authorization: `Bearer ${session.apiKey}`,
        "x-posthog-mcp-consumer": CONSUMER,
      },
    },
  });
  const client = new Client(
    { name: "mobilehog", version: "1.0.0" },
    { capabilities: {} },
  );
  const ready = client.connect(transport).then(() => client);
  ready.catch(() => {
    if (connection?.key === key) connection = null;
  });
  connection = { key, client: ready };
  return ready;
}

export async function readMcpResource(
  uri: string,
): Promise<ReadResourceResult> {
  const client = await getClient();
  return (await client.readResource({ uri })) as ReadResourceResult;
}

export async function callMcpTool(
  name: string,
  args?: Record<string, unknown>,
): Promise<CallToolResult> {
  const client = await getClient();
  return (await client.callTool({
    name,
    arguments: args ?? {},
  })) as CallToolResult;
}

let tools: Promise<Tool[]> | null = null;

export function listMcpTools(): Promise<Tool[]> {
  if (!tools) {
    tools = getClient()
      .then((client) => client.listTools())
      .then((result) => result.tools);
    tools.catch(() => {
      tools = null;
    });
  }
  return tools;
}
