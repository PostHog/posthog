import { randomBytes } from "node:crypto";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { TASK_BROWSER_SERVICE } from "@posthog/core/task-browser/identifiers";
import type { TaskBrowserService } from "@posthog/core/task-browser/taskBrowserService";
import type { AgentTaskBrowser } from "@posthog/workspace-server/services/agent/identifiers";
import { inject, injectable } from "inversify";

const MAX_BODY_BYTES = 256_000;

@injectable()
export class BrowserMcpHttpServer implements AgentTaskBrowser {
  private server: http.Server | null = null;
  private listening: Promise<number> | null = null;
  private readonly tokens = new Map<string, string>();

  constructor(
    @inject(TASK_BROWSER_SERVICE)
    private readonly service: TaskBrowserService,
  ) {}

  async localConnection(
    taskId: string,
  ): Promise<{ url: string; token: string }> {
    const port = await this.start();
    let token = [...this.tokens.entries()].find(([, id]) => id === taskId)?.[0];
    if (!token) {
      token = randomBytes(24).toString("hex");
      this.tokens.set(token, taskId);
    }
    return { url: `http://127.0.0.1:${port}/mcp`, token };
  }

  release(taskId: string): void {
    for (const [token, id] of this.tokens) {
      if (id === taskId) this.tokens.delete(token);
    }
    this.service.forgetTask(taskId);
  }

  private start(): Promise<number> {
    if (this.listening) return this.listening;
    this.listening = new Promise<number>((resolve, reject) => {
      const server = http.createServer(
        (req, res) => void this.onRequest(req, res),
      );
      server.once("error", reject);
      server.listen(0, "127.0.0.1", () => {
        this.server = server;
        resolve((server.address() as AddressInfo).port);
      });
    }).catch((error: unknown) => {
      this.listening = null;
      throw error;
    });
    return this.listening;
  }

  private async onRequest(req: http.IncomingMessage, res: http.ServerResponse) {
    const auth = req.headers.authorization ?? "";
    const taskId = auth.startsWith("Bearer ")
      ? this.tokens.get(auth.slice("Bearer ".length))
      : undefined;
    if (!taskId || req.url !== "/mcp") {
      res.writeHead(401).end();
      return;
    }
    if (req.method !== "POST") {
      res.writeHead(405, { Allow: "POST" }).end();
      return;
    }
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const chunk of req) {
      size += (chunk as Buffer).length;
      if (size > MAX_BODY_BYTES) {
        res.writeHead(413).end();
        return;
      }
      chunks.push(chunk as Buffer);
    }
    let payload: unknown;
    try {
      payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    } catch {
      res.writeHead(400).end();
      return;
    }
    const messages = Array.isArray(payload) ? payload : [payload];
    const responses = (
      await Promise.all(
        messages.map((message) =>
          message && typeof message === "object"
            ? this.service.mcp.handle(
                taskId,
                message as Record<string, unknown>,
              )
            : null,
        ),
      )
    ).filter((response) => response !== null);
    if (responses.length === 0) {
      res.writeHead(202).end();
      return;
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(Array.isArray(payload) ? responses : responses[0]));
  }

  close(): void {
    this.server?.close();
    this.server = null;
    this.listening = null;
  }
}
