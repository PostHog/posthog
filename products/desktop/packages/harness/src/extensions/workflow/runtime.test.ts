import { describe, expect, it, vi } from "vitest";
import type {
  WorkflowAgentRequest,
  WorkflowHooks,
  WorkflowRunOptions,
} from "./runtime";
import {
  checkAgainstSchema,
  extractDeclaredPlan,
  extractWorkflowName,
  extractWorkflowPhaseMetadata,
  extractWorkflowPhases,
  normalizeWorkflowScript,
  parseJsonLoose,
  runWorkflowScript,
} from "./runtime";

function options(
  overrides: Partial<WorkflowRunOptions> = {},
): WorkflowRunOptions {
  return { agentNames: ["Explore", "Plan"], cwd: "/tmp", ...overrides };
}

function hooks(
  runAgentTask: WorkflowHooks["runAgentTask"] = async ({ prompt }) => ({
    output: `echo: ${prompt}`,
  }),
  overrides: Partial<WorkflowHooks> = {},
): WorkflowHooks {
  return { runAgentTask, ...overrides };
}

describe("normalizeWorkflowScript", () => {
  it.each([
    ["strips markdown fences", "```js\nreturn 1\n```", "return 1"],
    [
      "demotes export const meta",
      "export const meta = { name: 'x' }\nreturn 1",
      "const meta = { name: 'x' }\nreturn 1",
    ],
    ["leaves plain scripts alone", "return 1", "return 1"],
  ])("%s", (_name, input, expected) => {
    expect(normalizeWorkflowScript(input)).toBe(expected);
  });
});

describe("extractWorkflowName", () => {
  it("finds meta.name", () => {
    expect(
      extractWorkflowName(
        "const meta = { name: 'audit_routes', description: 'd' }",
      ),
    ).toBe("audit_routes");
  });

  it("returns undefined when absent", () => {
    expect(extractWorkflowName("return 1")).toBeUndefined();
  });
});

describe("extractWorkflowPhases", () => {
  it("lists static phase calls in source order without duplicates", () => {
    expect(
      extractWorkflowPhases(
        `phase("Explore")\nphase('Compare')\nphase("Explore")\nphase(name)`,
      ),
    ).toEqual(["Explore", "Compare"]);
  });

  it("extracts literal phase metadata before the workflow starts", () => {
    expect(
      extractWorkflowPhaseMetadata(
        `phase('Scan', { goal: 'Map routes', inputs: ['repo'], produces: ['inventory'] })`,
      ),
    ).toEqual([
      {
        title: "Scan",
        metadata: {
          goal: "Map routes",
          inputs: ["repo"],
          produces: ["inventory"],
        },
      },
    ]);
  });
});

describe("parseJsonLoose", () => {
  it.each([
    ["plain JSON", '{"a":1}', { a: 1 }],
    ["fenced JSON", 'Here:\n```json\n{"a":1}\n```\ndone', { a: 1 }],
    ["JSON embedded in prose", 'The result is {"a":1} as requested.', { a: 1 }],
    ["arrays", "[1,2,3]", [1, 2, 3]],
  ])("parses %s", (_name, input, expected) => {
    expect(parseJsonLoose(input)).toEqual(expected);
  });

  it("throws when no JSON is present", () => {
    expect(() => parseJsonLoose("no json here")).toThrow(/no JSON/);
  });
});

describe("checkAgainstSchema", () => {
  it.each([
    ["object matching", { a: 1 }, { type: "object", required: ["a"] }],
    ["array matching", [1], { type: "array" }],
    ["untyped schema", "anything", {}],
  ])("accepts %s", (_name, value, schema) => {
    expect(() =>
      checkAgainstSchema(value, schema as Record<string, unknown>),
    ).not.toThrow();
  });

  it.each([
    ["non-object", "text", { type: "object" }, /expected an object/],
    [
      "missing required key",
      { a: 1 },
      { type: "object", required: ["a", "b"] },
      /missing required key\(s\) b/,
    ],
    ["non-array", { a: 1 }, { type: "array" }, /expected an array/],
  ])("rejects %s", (_name, value, schema, message) => {
    expect(() =>
      checkAgainstSchema(value, schema as Record<string, unknown>),
    ).toThrow(message);
  });
});

describe("runWorkflowScript", () => {
  it("parses a literal declared plan without executing metadata", async () => {
    expect(
      extractDeclaredPlan(
        `const meta = { name: 'x', inputs: ['repo'], phases: [{ title: 'Scan', inputs: ['repo'], produces: ['inventory'] }], synthesis: { phase: 'Scan', inputs: ['repo'], produces: ['inventory'] } }`,
      ),
    ).toMatchObject({ name: "x", phases: [{ title: "Scan" }] });
    expect(extractDeclaredPlan("const meta = makePlan()")).toBeUndefined();
  });

  it("hands published strict-plan artifacts to the next agent without exposing values in hooks", async () => {
    const runAgentTask = vi.fn(async ({ task }: WorkflowAgentRequest) => ({
      output: task === "scan" ? "inventory" : "final",
    }));
    const artifacts: string[] = [];
    await runWorkflowScript(
      `const meta = { name: 'x', inputs: ['repo'], phases: [{ title: 'Scan', inputs: ['repo'], produces: ['inventory'] }, { title: 'Synthesize', inputs: ['inventory'], produces: ['verdict'] }], synthesis: { phase: 'Synthesize', inputs: ['inventory'], produces: ['verdict'] } }
      phase('Scan'); await agent('scan', { inputs: ['repo'], produces: 'inventory' }); phase('Synthesize'); return await agent('summarize', { inputs: ['inventory'], produces: 'verdict' });`,
      options({ args: { repo: "source" } }),
      hooks(runAgentTask, {
        onArtifact: (artifact) => artifacts.push(artifact.name),
      }),
    );
    expect(runAgentTask.mock.calls[1][0].prompt).toContain(
      '"inventory": "inventory"',
    );
    expect(artifacts).toEqual(["inventory", "verdict"]);
  });

  it("preflights invalid strict dependencies before running children", async () => {
    const task = vi.fn();
    await expect(
      runWorkflowScript(
        `const meta = { name: 'x', inputs: [], phases: [{ title: 'Scan', inputs: ['missing'], produces: ['a'] }], synthesis: { phase: 'Scan', inputs: [], produces: ['a'] } }; phase('Scan'); return await agent('x', { inputs: [], produces: 'a' })`,
        options(),
        hooks(task),
      ),
    ).rejects.toThrow(/requires "missing"/);
    expect(task).not.toHaveBeenCalled();
  });

  it("keeps legacy scripts compatible without phase declarations", async () => {
    await expect(
      runWorkflowScript(
        `return await agent('x', { inputs: { inline: 'value' } })`,
        options(),
        hooks(),
      ),
    ).resolves.toMatchObject({ result: expect.stringContaining("echo: x") });
  });

  it("runs agents and returns the script result", async () => {
    const runAgentTask = vi.fn(async ({ prompt }: { prompt: string }) => ({
      output: `out(${prompt})`,
    }));
    const outcome = await runWorkflowScript(
      `export const meta = { name: 'test', description: 'd' }
       phase('Scan')
       const a = await agent('one', { label: 'first' })
       return { a }`,
      options(),
      hooks(runAgentTask),
    );

    expect(outcome.result).toEqual({ a: "out(one)" });
    expect(outcome.agentCount).toBe(1);
    expect(outcome.phases).toEqual(["Scan"]);
    expect(runAgentTask).toHaveBeenCalledWith(
      expect.objectContaining({
        prompt: "one",
        agent: "Explore",
        label: "first",
        phase: "Scan",
      }),
      undefined,
    );
  });

  it("carries phase and agent metadata and injects concise child context", async () => {
    const runAgentTask = vi.fn(async (_request: WorkflowAgentRequest) => ({
      output: "ok",
    }));
    const onPhase = vi.fn();
    await runWorkflowScript(
      `phase('Scan', { goal: 'Map code', inputs: ['repo'], produces: ['inventory'] })
       return await agent('Inspect routes', {
         objective: 'Identify route files',
         inputs: { source: 'inventory' },
         produces: 'route-audit',
         schema: { type: 'object', required: ['files'] },
       })`,
      options(),
      hooks(runAgentTask, { onPhase }),
    );
    expect(onPhase).toHaveBeenCalledWith("Scan", {
      goal: "Map code",
      inputs: ["repo"],
      produces: ["inventory"],
    });
    expect(runAgentTask).toHaveBeenCalledWith(
      expect.objectContaining({
        task: "Inspect routes",
        objective: "Identify route files",
        inputs: { source: "inventory" },
        produces: "route-audit",
        prompt: expect.stringContaining("Workflow context:"),
      }),
      undefined,
    );
    expect(runAgentTask.mock.calls[0][0].prompt).toContain("Output contract:");
  });

  it("rejects malformed workflow metadata as a fatal script bug", async () => {
    await expect(
      runWorkflowScript(
        `phase('Scan', { inputs: 'repo' }); return await agent('x', { inputs: [1] })`,
        options(),
        hooks(),
      ),
    ).rejects.toThrow(/phase inputs must be an array/);
  });

  it("runs parallel thunks and preserves order", async () => {
    const outcome = await runWorkflowScript(
      `return await parallel(['a', 'b', 'c'].map(x => () => agent(x)))`,
      options(),
      hooks(),
    );
    expect(outcome.result).toEqual(["echo: a", "echo: b", "echo: c"]);
    expect(outcome.agentCount).toBe(3);
  });

  it("rejects parallel() given promises instead of thunks", async () => {
    await expect(
      runWorkflowScript(
        `return await parallel([agent('a')])`,
        options(),
        hooks(),
      ),
    ).rejects.toThrow(/array of functions/);
  });

  it("runs pipeline stages in order per item, items concurrently", async () => {
    const outcome = await runWorkflowScript(
      `return await pipeline(
         ['a', 'b'],
         (item) => agent('scan ' + item),
         (prev, original, index) => agent('verify ' + prev + '/' + original + '/' + index),
       )`,
      options(),
      hooks(),
    );
    expect(outcome.result).toEqual([
      "echo: verify echo: scan a/a/0",
      "echo: verify echo: scan b/b/1",
    ]);
    expect(outcome.agentCount).toBe(4);
  });

  it("nulls out a pipeline item whose stage fails, others continue", async () => {
    const outcome = await runWorkflowScript(
      `return await pipeline(['good', 'bad'], (item) => agent(item))`,
      options(),
      hooks(async ({ prompt }) => {
        if (prompt.includes("bad")) throw new Error("kaput");
        return { output: "ok" };
      }),
    );
    // The agent-level failure already nulls the value; pipeline passes it on.
    expect(outcome.result).toEqual(["ok", null]);
    expect(outcome.logs.some((l) => l.includes("kaput"))).toBe(true);
  });

  it("rejects pipeline() without function stages", async () => {
    await expect(
      runWorkflowScript(`return await pipeline(['a'])`, options(), hooks()),
    ).rejects.toThrow(/stages must be functions/);
  });

  it("turns a failed agent into null plus a log line", async () => {
    const outcome = await runWorkflowScript(
      `const a = await agent('boom', { label: 'exploder' })
       return { a }`,
      options(),
      hooks(async () => {
        throw new Error("kaput");
      }),
    );
    expect(outcome.result).toEqual({ a: null });
    expect(outcome.logs).toEqual(['agent "exploder" failed: kaput']);
  });

  it("rejects unknown agent names", async () => {
    await expect(
      runWorkflowScript(
        `return await agent('x', { agent: 'Hacker' })`,
        options(),
        hooks(),
      ),
    ).rejects.toThrow(/Unknown agent "Hacker"/);
  });

  it("enforces the agent cap", async () => {
    await expect(
      runWorkflowScript(
        `for (let i = 0; i < 5; i++) await agent('x')
         return 'done'`,
        options({ maxAgents: 3 }),
        hooks(),
      ),
    ).rejects.toThrow(/agent limit reached \(3\)/);
  });

  it("limits concurrency", async () => {
    let active = 0;
    let peak = 0;
    const outcome = await runWorkflowScript(
      `return await parallel([1,2,3,4,5,6].map(x => () => agent('t' + x)))`,
      options({ concurrency: 2 }),
      hooks(async () => {
        active++;
        peak = Math.max(peak, active);
        await new Promise((resolve) => setTimeout(resolve, 5));
        active--;
        return { output: "ok" };
      }),
    );
    expect(outcome.agentCount).toBe(6);
    expect(peak).toBeLessThanOrEqual(2);
  });

  describe("schema option", () => {
    it("returns the parsed, shape-checked object and embeds the contract in the prompt", async () => {
      const runAgentTask = vi.fn(async (_request: WorkflowAgentRequest) => ({
        output: 'Sure!\n```json\n{"files": ["a.ts"]}\n```',
      }));
      const outcome = await runWorkflowScript(
        `return await agent('list files', {
           label: 'inventory',
           schema: { type: 'object', required: ['files'], properties: { files: { type: 'array' } } },
         })`,
        options(),
        hooks(runAgentTask),
      );
      expect(outcome.result).toEqual({ files: ["a.ts"] });
      const prompt = runAgentTask.mock.calls[0][0].prompt;
      expect(prompt).toContain("list files");
      expect(prompt).toContain("Output contract");
      expect(prompt).toContain('"required"');
    });

    it("parses complete structured output before applying model truncation", async () => {
      const outcome = await runWorkflowScript(
        `return await agent('list files', {
           schema: { type: 'object', required: ['files'] },
         })`,
        options(),
        hooks(async () => ({
          output: '{"files": ["a.ts"]}',
          modelOutput: '{"files"',
        })),
      );
      expect(outcome.result).toEqual({ files: ["a.ts"] });
    });

    it("treats schema violations as agent failure (null + log)", async () => {
      const outcome = await runWorkflowScript(
        `return await agent('list files', {
           label: 'inventory',
           schema: { type: 'object', required: ['files'] },
         })`,
        options(),
        hooks(async () => ({ output: '{"wrong": true}' })),
      );
      expect(outcome.result).toBeNull();
      expect(outcome.logs[0]).toMatch(/missing required key\(s\) files/);
    });

    it("rejects non-object schema values", async () => {
      await expect(
        runWorkflowScript(
          `return await agent('x', { schema: 'not a schema' })`,
          options(),
          hooks(),
        ),
      ).rejects.toThrow(/schema must be a plain JSON Schema object/);
    });
  });

  describe("model option", () => {
    it("passes the model string through to the request untouched (tier resolution is extension.ts's job)", async () => {
      const runAgentTask = vi.fn(async (_request: WorkflowAgentRequest) => ({
        output: "x",
      }));
      await runWorkflowScript(
        `return await agent('x', { model: 'strong' })`,
        options(),
        hooks(runAgentTask),
      );
      expect(runAgentTask).toHaveBeenCalledWith(
        expect.objectContaining({ model: "strong" }),
        undefined,
      );
    });

    it("omitting model leaves the request's model undefined", async () => {
      const runAgentTask = vi.fn(async (_request: WorkflowAgentRequest) => ({
        output: "x",
      }));
      await runWorkflowScript(
        `return await agent('x')`,
        options(),
        hooks(runAgentTask),
      );
      expect(runAgentTask).toHaveBeenCalledWith(
        expect.objectContaining({ model: undefined }),
        undefined,
      );
    });

    it("rejects a non-string model as a fatal script bug, not a swallowed failure", async () => {
      await expect(
        runWorkflowScript(
          `return await parallel([1].map(() => () => agent('x', { model: 42 })))`,
          options(),
          hooks(),
        ),
      ).rejects.toThrow(/model must be a non-empty string/);
    });
  });

  it("propagates aborts instead of swallowing them", async () => {
    const controller = new AbortController();
    await expect(
      runWorkflowScript(
        `return await agent('slow')`,
        options({ signal: controller.signal }),
        hooks(async (_request, signal) => {
          controller.abort();
          if (signal?.aborted) throw new Error("aborted");
          return { output: "unreachable" };
        }),
      ),
    ).rejects.toThrow(/abort/i);
  });

  it("blocks host escape hatches", async () => {
    await expect(
      runWorkflowScript(`return require('fs')`, options(), hooks()),
    ).rejects.toThrow();
    await expect(
      runWorkflowScript(`return typeof fetch`, options(), hooks()),
    ).resolves.toMatchObject({ result: "undefined" });
  });

  describe("sandbox hardening", () => {
    it("does not leak the host realm via injected built-ins (Array/Object/JSON/etc)", async () => {
      // Regression test: the sandbox must use vm's own context-native
      // built-ins, never the host module's real Array/Object/JSON/etc —
      // handing those over directly would make e.g.
      // `Array.constructor('return process')()` a one-line host escape.
      const outcome = await runWorkflowScript(
        `const leaked = Array.constructor('return typeof process')();
         return { leaked }`,
        options(),
        hooks(),
      );
      expect(outcome.result).toEqual({ leaked: "undefined" });
    });

    it("does not leak the host realm via an exposed function's own prototype chain", async () => {
      // `agent`/`parallel`/etc must themselves be host-realm functions (they
      // do real work), but their prototype is stripped so the laziest gadget
      // (`Object.getPrototypeOf(fn).constructor(...)`) can't reach `Function`.
      const outcome = await runWorkflowScript(
        `let leaked = 'blocked'
         try {
           const hostFn = Object.getPrototypeOf(agent).constructor
           leaked = hostFn('return typeof process')()
         } catch (e) { leaked = 'blocked: ' + e.constructor.name }
         return { leaked }`,
        options(),
        hooks(),
      );
      expect(outcome.result).toEqual({ leaked: "blocked: TypeError" });
    });

    it("interrupts a synchronous infinite loop instead of hanging the process forever", async () => {
      const start = Date.now();
      await expect(
        runWorkflowScript(
          `while (true) {}`,
          options({ syncTimeoutMs: 200 }),
          hooks(),
        ),
      ).rejects.toThrow(/timed out/i);
      expect(Date.now() - start).toBeLessThan(2000);
    });

    it("still allows normal synchronous work within the timeout", async () => {
      const outcome = await runWorkflowScript(
        `let sum = 0
         for (let i = 0; i < 1e6; i++) sum += i
         return sum > 0`,
        options({ syncTimeoutMs: 200 }),
        hooks(),
      );
      expect(outcome.result).toBe(true);
    });
  });

  it("explains module-syntax errors with a hint", async () => {
    await expect(
      runWorkflowScript(`import fs from 'fs'\nreturn 1`, options(), hooks()),
    ).rejects.toThrow(/remove import\/export statements/);
  });

  it("explains TypeScript-syntax errors with a hint", async () => {
    await expect(
      runWorkflowScript(
        `const x: string = 'a'\nreturn await agent(x)`,
        options(),
        hooks(),
      ),
    ).rejects.toThrow(/plain JavaScript, not TypeScript/);
  });

  it("includes a source location for syntax errors", async () => {
    await expect(
      runWorkflowScript(
        `const config = { label: "one" }}\nreturn await agent("x", config)`,
        options(),
        hooks(),
      ),
    ).rejects.toThrow(/workflow\.js:\d+/);
  });

  it("exposes args and parseJson to the script", async () => {
    const outcome = await runWorkflowScript(
      `const parsed = parseJson(await agent('give json'))
       return { parsed, args }`,
      options({ args: { limit: 2 } }),
      hooks(async () => ({ output: 'Sure!\n```json\n{"ok":true}\n```' })),
    );
    expect(outcome.result).toEqual({
      parsed: { ok: true },
      args: { limit: 2 },
    });
  });

  describe("result serializability", () => {
    it("rejects non-serializable results (unawaited promises)", async () => {
      await expect(
        runWorkflowScript(`return { p: agent('x') }`, options(), hooks()),
      ).rejects.toThrow(/forget to await/);
    });

    it("rejects circular results with a clear message instead of letting them through", async () => {
      // structuredClone (the previous check) happily accepts circular refs;
      // JSON.stringify (what the rest of the pipeline actually needs) does
      // not. Must fail here, not downstream in an uncontrolled serializer.
      await expect(
        runWorkflowScript(
          `const o = {}; o.self = o; return o`,
          options(),
          hooks(),
        ),
      ).rejects.toThrow(/JSON-serializable/);
    });

    it("rejects BigInt results with a clear message", async () => {
      // structuredClone supports BigInt; JSON.stringify throws on it.
      await expect(
        runWorkflowScript(`return { big: 10n }`, options(), hooks()),
      ).rejects.toThrow(/JSON-serializable/);
    });

    it("still allows ordinary JSON-shaped results", async () => {
      const outcome = await runWorkflowScript(
        `await agent('x')
         return { a: [1, 2, { b: 'c' }], d: null, e: true }`,
        options(),
        hooks(),
      );
      expect(outcome.result).toEqual({
        a: [1, 2, { b: "c" }],
        d: null,
        e: true,
      });
    });
  });

  describe("fatal vs. tolerated failures inside parallel()/pipeline()", () => {
    it("still tolerates an ordinary subagent execution failure as null + log", async () => {
      const outcome = await runWorkflowScript(
        `return await parallel([1, 2].map(n => () => agent('t' + n, { label: 'l' + n })))`,
        options(),
        hooks(async () => {
          throw new Error("subagent blew up");
        }),
      );
      expect(outcome.result).toEqual([null, null]);
      expect(outcome.logs).toHaveLength(2);
    });

    it("does not swallow an unknown-agent script bug inside parallel()", async () => {
      // Previously: every item silently nulled with a confusing per-item log
      // line instead of one clear top-level failure explaining the real bug.
      await expect(
        runWorkflowScript(
          `return await parallel([1, 2, 3].map(() => () => agent('x', { agent: 'Ghost' })))`,
          options(),
          hooks(),
        ),
      ).rejects.toThrow(/Unknown agent "Ghost"/);
    });

    it("does not swallow an agent-cap violation inside parallel(), matching top-level behavior", async () => {
      await expect(
        runWorkflowScript(
          `return await parallel(Array.from({ length: 10 }, (_, i) => () => agent('t' + i)))`,
          options({ maxAgents: 3 }),
          hooks(),
        ),
      ).rejects.toThrow(/agent limit reached \(3\)/);
    });

    it("does not swallow the same fatal errors inside pipeline()", async () => {
      await expect(
        runWorkflowScript(
          `return await pipeline([1, 2], (n) => agent('t' + n, { agent: 'Ghost' }))`,
          options(),
          hooks(),
        ),
      ).rejects.toThrow(/Unknown agent "Ghost"/);
    });

    it("still tolerates a schema mismatch as null + log (content failure, not a script bug)", async () => {
      const outcome = await runWorkflowScript(
        `return await parallel([1].map(() => () => agent('x', { schema: { type: 'object', required: ['files'] } })))`,
        options(),
        hooks(async () => ({ output: '{"nope": true}' })),
      );
      expect(outcome.result).toEqual([null]);
    });
  });

  it("reports one stable agent ID to task and lifecycle hooks", async () => {
    const ids: number[] = [];
    await runWorkflowScript(
      `phase('P1')
       await agent('a', { label: 'one' })
       return 'ok'`,
      options(),
      hooks(
        async (event) => {
          ids.push(event.id);
          return { output: "ok" };
        },
        {
          onAgentStart: (event) => ids.push(event.id),
          onAgentEnd: (event) => ids.push(event.id),
        },
      ),
    );
    expect(ids).toEqual([1, 1, 1]);
  });
});
