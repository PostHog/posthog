/**
 * Bridges the phrocs MCP server (tools/phrocs/mcp_server.py) into pi as
 * first-class tools. Speaks the MCP stdio JSON-RPC 2.0 wire protocol
 * directly — no @modelcontextprotocol/sdk dependency, so there is no
 * node_modules to install. Drop the repo, run pi, the tools appear.
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { spawn, type ChildProcess } from "node:child_process";
import { Type, type TSchema } from "typebox";

const PROTOCOL_VERSION = "2024-11-05";
const CLIENT_NAME = "posthog-pi-phrocs";
const CLIENT_VERSION = "1.0.0";
const STATUS_KEY = "phrocs-mcp";
const SERVER_CMD = "uv";
const SERVER_ARGS = ["run", "python", "tools/phrocs/mcp_server.py"];
const REQUEST_TIMEOUT_MS = 60_000;
const STDERR_TAIL_BYTES = 8 * 1024;

interface JsonRpcResponse {
    jsonrpc: "2.0";
    id: number;
    result?: unknown;
    error?: { code: number; message: string; data?: unknown };
}

interface JsonSchema {
    type?: string;
    description?: string;
    properties?: Record<string, JsonSchema>;
    required?: string[];
    items?: JsonSchema;
    enum?: (string | number | boolean)[];
    default?: unknown;
    minimum?: number;
    maximum?: number;
    anyOf?: JsonSchema[];
    oneOf?: JsonSchema[];
}

interface McpTool {
    name: string;
    title?: string;
    description?: string;
    inputSchema?: JsonSchema;
}

interface McpToolResult {
    content?: Array<{ type: string; text?: string }>;
    isError?: boolean;
    structuredContent?: unknown;
}

class McpStdioClient {
    private proc: ChildProcess | null = null;
    private nextId = 1;
    private pending = new Map<
        number,
        { resolve: (v: unknown) => void; reject: (e: Error) => void; timer: unknown; onAbort?: () => void; signal?: AbortSignal }
    >();
    private buffer = "";
    private stderrTail = "";

    async start(command: string, args: string[], cwd: string): Promise<McpTool[]> {
        this.proc = spawn(command, args, {
            cwd,
            stdio: ["pipe", "pipe", "pipe"],
            env: { ...process.env },
        });

        const stdout = this.proc.stdout;
        const stderr = this.proc.stderr;
        if (!stdout || !this.proc.stdin) {
            throw new Error("failed to open phrocs MCP server stdio");
        }
        stdout.setEncoding("utf8");
        stdout.on("data", (chunk: string) => this.onData(chunk));
        // Capture a rolling tail of stderr so startup failures (missing uv,
        // import errors, etc.) show up in error messages and /phrocs-status.
        stderr?.setEncoding("utf8");
        stderr?.on("data", (chunk: string) => this.appendStderr(chunk));

        this.proc.on("error", (err) => this.failPending(err));
        this.proc.on("exit", (code) => {
            const tail = this.stderrTail.trim();
            const detail = tail ? `: ${tail.slice(-500)}` : "";
            this.failPending(new Error(`phrocs MCP server exited (code=${code})${detail}`));
        });

        await this.request("initialize", {
            protocolVersion: PROTOCOL_VERSION,
            capabilities: {},
            clientInfo: { name: CLIENT_NAME, version: CLIENT_VERSION },
        });
        this.notify("notifications/initialized", {});

        const listed = (await this.request("tools/list", {})) as { tools?: McpTool[] };
        return listed.tools ?? [];
    }

    async callTool(name: string, args: Record<string, unknown>, signal?: AbortSignal): Promise<McpToolResult> {
        return (await this.request("tools/call", { name, arguments: args }, signal)) as McpToolResult;
    }

    stderrSnapshot(): string {
        return this.stderrTail;
    }

    async close(): Promise<void> {
        const proc = this.proc;
        if (!proc) return;
        this.proc = null;
        this.failPending(new Error("phrocs MCP client closing"));
        proc.stdin?.end();
        await new Promise<void>((resolve) => {
            const timer = setTimeout(() => {
                proc.kill("SIGKILL");
                resolve();
            }, 2000);
            proc.once("exit", () => {
                clearTimeout(timer);
                resolve();
            });
            proc.kill("SIGTERM");
        });
    }

    private appendStderr(chunk: string): void {
        this.stderrTail = (this.stderrTail + chunk).slice(-STDERR_TAIL_BYTES);
    }

    private onData(chunk: string): void {
        this.buffer += chunk;
        let idx = this.buffer.indexOf("\n");
        while (idx >= 0) {
            const line = this.buffer.slice(0, idx).trim();
            this.buffer = this.buffer.slice(idx + 1);
            if (line) this.onLine(line);
            idx = this.buffer.indexOf("\n");
        }
    }

    private onLine(line: string): void {
        let msg: JsonRpcResponse;
        try {
            msg = JSON.parse(line);
        } catch {
            return;
        }
        if (typeof msg.id !== "number") return;
        const waiting = this.pending.get(msg.id);
        if (!waiting) return;
        this.pending.delete(msg.id);
        clearTimeout(waiting.timer);
        if (waiting.onAbort && waiting.signal) {
            waiting.signal.removeEventListener("abort", waiting.onAbort);
        }
        if (msg.error) {
            waiting.reject(new Error(`${msg.error.message} (code ${msg.error.code})`));
        } else {
            waiting.resolve(msg.result);
        }
    }

    private request(method: string, params: unknown, signal?: AbortSignal): Promise<unknown> {
        return new Promise((resolve, reject) => {
            const stdin = this.proc?.stdin;
            if (!stdin) {
                reject(new Error("phrocs MCP server not started"));
                return;
            }
            if (signal?.aborted) {
                reject(new Error("phrocs MCP request aborted"));
                return;
            }
            const id = this.nextId++;
            const timer = setTimeout(() => {
                if (!this.pending.delete(id)) return;
                reject(new Error(`phrocs MCP request '${method}' timed out after ${REQUEST_TIMEOUT_MS}ms`));
            }, REQUEST_TIMEOUT_MS);
            const onAbort = signal
                ? () => {
                      if (!this.pending.delete(id)) return;
                      clearTimeout(timer);
                      reject(new Error("phrocs MCP request aborted"));
                  }
                : undefined;
            if (signal && onAbort) signal.addEventListener("abort", onAbort, { once: true });
            this.pending.set(id, { resolve, reject, timer, onAbort, signal });
            stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`, (err) => {
                if (err && this.pending.delete(id)) {
                    clearTimeout(timer);
                    if (signal && onAbort) signal.removeEventListener("abort", onAbort);
                    reject(err);
                }
            });
        });
    }

    private notify(method: string, params: unknown): void {
        this.proc?.stdin?.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
    }

    private failPending(err: Error): void {
        for (const waiter of this.pending.values()) {
            clearTimeout(waiter.timer);
            if (waiter.onAbort && waiter.signal) waiter.signal.removeEventListener("abort", waiter.onAbort);
            waiter.reject(err);
        }
        this.pending.clear();
    }
}

function jsonSchemaToTypeBox(schema: JsonSchema | undefined): TSchema {
    if (!schema || typeof schema !== "object") return Type.Object({});
    const type = schema.type;
    const description = schema.description;

    if (type === "object" || (!type && schema.properties)) {
        const required = new Set(schema.required ?? []);
        const props: Record<string, TSchema> = {};
        for (const [key, value] of Object.entries(schema.properties ?? {})) {
            const child = jsonSchemaToTypeBox(value);
            props[key] = required.has(key) ? child : Type.Optional(child);
        }
        return Type.Object(props, { description });
    }
    if (type === "string") {
        if (schema.enum?.length) {
            const literals = schema.enum.map((v) => Type.Literal(v));
            return literals.length === 1 ? literals[0] : Type.Union(literals, { description });
        }
        return Type.String({ description, default: schema.default as string | undefined });
    }
    if (type === "integer" || type === "number") {
        return Type.Number({
            description,
            default: schema.default as number | undefined,
            minimum: schema.minimum,
            maximum: schema.maximum,
        });
    }
    if (type === "boolean") {
        return Type.Boolean({ description, default: schema.default as boolean | undefined });
    }
    if (type === "array") {
        return Type.Array(jsonSchemaToTypeBox(schema.items ?? {}), { description });
    }
    if (type === "null") return Type.Null();
    if (schema.anyOf?.length || schema.oneOf?.length) {
        const variants = (schema.anyOf?.length ? schema.anyOf : schema.oneOf)!;
        return Type.Union(variants.map(jsonSchemaToTypeBox), { description });
    }
    return Type.Any({ description });
}

function formatToolResult(result: McpToolResult): string {
    const parts = (result.content ?? [])
        .filter((c) => c.type === "text" && typeof c.text === "string")
        .map((c) => c.text as string);
    if (parts.length > 0) return parts.join("\n");
    if (result.structuredContent !== undefined) {
        return typeof result.structuredContent === "string"
            ? result.structuredContent
            : JSON.stringify(result.structuredContent, null, 2);
    }
    return "";
}

export default function registerPhrocsExtension(pi: ExtensionAPI) {
    let client: McpStdioClient | null = null;
    let startup: Promise<void> | null = null;
    let lastError: string | null = null;
    const registered = new Set<string>();

    const setStatus = (text: string | undefined, ctx?: ExtensionContext) => {
        ctx?.ui?.setStatus(STATUS_KEY, text);
    };

    const connect = async (ctx: ExtensionContext): Promise<void> => {
        if (client) return;
        if (startup) return startup;

        setStatus("phrocs: starting…", ctx);
        const next = new McpStdioClient();
        startup = (async () => {
            try {
                const tools = await next.start(SERVER_CMD, SERVER_ARGS, ctx.cwd);
                client = next;
                lastError = null;

                for (const tool of tools) {
                    // Pi has no unregister API, so once a tool is registered
                    // it stays for the session. Skip silently on reconnect.
                    if (registered.has(tool.name)) continue;
                    if (pi.getAllTools().some((existing) => existing.name === tool.name)) {
                        ctx.ui?.notify(`phrocs: skipped '${tool.name}' (name collision)`, "warning");
                        continue;
                    }
                    registered.add(tool.name);
                    pi.registerTool({
                        name: tool.name,
                        label: tool.title ?? tool.name,
                        description: tool.description ?? `phrocs MCP tool: ${tool.name}`,
                        parameters: jsonSchemaToTypeBox(tool.inputSchema),
                        async execute(_toolCallId, params, signal) {
                            if (!client) throw new Error("phrocs MCP client not connected");
                            const result = await client.callTool(tool.name, params as Record<string, unknown>, signal);
                            const text = formatToolResult(result);
                            if (result.isError) {
                                throw new Error(text || `phrocs tool '${tool.name}' returned an error`);
                            }
                            return {
                                content: [{ type: "text", text }],
                                details: {},
                            };
                        },
                    });
                }

                setStatus(`phrocs: ${registered.size} tools`, ctx);
            } catch (err) {
                const tail = next.stderrSnapshot().trim();
                const base = err instanceof Error ? err.message : String(err);
                lastError = tail ? `${base}\n--- stderr tail ---\n${tail.slice(-500)}` : base;
                setStatus("phrocs: failed", ctx);
                ctx.ui?.notify(`phrocs MCP failed to start: ${lastError}`, "error");
                await next.close().catch(() => undefined);
            }
        })().finally(() => {
            startup = null;
        });

        return startup;
    };

    pi.on("session_start", async (_event, ctx) => {
        await connect(ctx);
    });

    pi.on("session_shutdown", async (_event, ctx) => {
        setStatus(undefined, ctx);
        const current = client;
        client = null;
        if (current) await current.close();
    });

    pi.registerCommand("phrocs-status", {
        description: "Show phrocs MCP connection status",
        handler: async (_args, ctx) => {
            const lines = [
                `connected: ${client !== null}`,
                `tools: ${registered.size}`,
                `last_error: ${lastError ?? "none"}`,
            ];
            const tail = client?.stderrSnapshot().trim();
            if (tail) lines.push(`stderr_tail:\n${tail.slice(-500)}`);
            ctx.ui.notify(lines.join("\n"), lastError ? "warning" : "info");
        },
    });

    pi.registerCommand("phrocs-reload", {
        description: "Reconnect to phrocs MCP (tool closures reuse the new client)",
        handler: async (_args, ctx) => {
            // Intentionally leave `registered` intact: pi has no unregister
            // API, so the existing tool closures stay wired up and transparently
            // use the new `client` after reconnect.
            const current = client;
            client = null;
            if (current) await current.close();
            await connect(ctx);
        },
    });
}
