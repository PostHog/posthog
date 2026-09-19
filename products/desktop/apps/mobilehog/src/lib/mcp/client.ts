import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type {
  CallToolResult,
  ReadResourceResult,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { MCP_HOSTS } from "@/config";
import { requireSession, sessionIdentity } from "@/lib/auth";

// The sandbox wrapper sends this too; it is what makes exec results carry the
// UI-app resource URI and structured data instead of plain text.
const CONSUMER = "posthog-code";

interface Connection {
  key: string;
  client: Promise<Client>;
  tools?: Promise<Tool[]>;
}

let connection: Connection | null = null;

export function resetMcpClient(): void {
  const previous = connection;
  connection = null;
  previous?.client.then((client) => client.close()).catch(() => {});
}

// One MCP client to the PostHog server for the signed-in host, opened lazily
// and reopened if the session changes.
function getConnection(): Connection {
  const session = requireSession();
  const key = `${sessionIdentity()}|${session.apiKey}`;
  if (connection?.key === key) return connection;
  resetMcpClient();
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
  const next: Connection = { key, client: ready };
  ready.catch(() => {
    if (connection === next) connection = null;
  });
  connection = next;
  return next;
}

async function getClient(): Promise<Client> {
  const current = getConnection();
  const client = await current.client;
  if (connection !== current)
    throw new Error("Session changed. Sign in again.");
  return client;
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

export function listMcpTools(): Promise<Tool[]> {
  const current = getConnection();
  if (!current.tools) {
    current.tools = getClient()
      .then((client) => client.listTools())
      .then((result) => result.tools);
    current.tools.catch(() => {
      current.tools = undefined;
    });
  }
  return current.tools;
}
