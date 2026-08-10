import { describe, expect, it } from "vitest";
import {
  buildPosthogPropertiesBlob,
  buildPosthogPropertiesHeaderLines,
  buildPosthogPropertiesHeaderRecord,
  buildPosthogPropertyHeaderLines,
  buildPosthogPropertyHeaderRecord,
} from "./posthog-property-headers";

describe("buildPosthogPropertyHeaderRecord", () => {
  it("returns each property as an x-posthog-property-<key> entry", () => {
    expect(
      buildPosthogPropertyHeaderRecord({
        task_origin_product: "signal_report",
        task_internal: true,
      }),
    ).toEqual({
      "x-posthog-property-task_origin_product": "signal_report",
      "x-posthog-property-task_internal": "true",
    });
  });

  it("drops null and undefined values but keeps falsy primitives", () => {
    expect(
      buildPosthogPropertyHeaderRecord({
        task_origin_product: null,
        task_internal: false,
        task_count: 0,
        skipped: undefined,
      }),
    ).toEqual({
      "x-posthog-property-task_internal": "false",
      "x-posthog-property-task_count": "0",
    });
  });

  it("returns an empty record when no usable properties remain", () => {
    expect(
      buildPosthogPropertyHeaderRecord({
        task_origin_product: null,
        task_internal: undefined,
      }),
    ).toEqual({});
  });

  it("collapses newline variants so a value cannot inject extra headers", () => {
    expect(
      buildPosthogPropertyHeaderRecord({
        task_title: "Fix the bug\r\nx-posthog-property-injected: true",
      }),
    ).toEqual({
      "x-posthog-property-task_title":
        "Fix the bug x-posthog-property-injected: true",
    });
  });

  it("strips characters an HTTP header value cannot carry", () => {
    expect(
      buildPosthogPropertyHeaderRecord({ task_title: "don’t🚀ship" }),
    ).toEqual({ "x-posthog-property-task_title": "dontship" });
  });

  it.each([
    {
      case: "precomposed accents (the incident title)",
      title: "sono più di 48 ore, è tardi",
      expected: "sono piu di 48 ore, e tardi",
    },
    {
      case: "combining marks already decomposed in the input",
      title: "cafe\u0301 al volo",
      expected: "cafe al volo",
    },
    {
      case: "NFKD compatibility forms (ligature, unit, fullwidth)",
      title: "ﬁle ㎏ Ｆｕｌｌ",
      expected: "file kg Full",
    },
    {
      case: "letters with no ASCII decomposition are dropped",
      title: "Ærøskøbing Straße",
      expected: "rskbing Strae",
    },
    {
      case: "fully non-Latin titles collapse to an empty value",
      title: "東京🎉",
      expected: "",
    },
  ])("$case", ({ title, expected }) => {
    expect(buildPosthogPropertyHeaderRecord({ task_title: title })).toEqual({
      "x-posthog-property-task_title": expected,
    });
  });

  // The regression class from the incident: any non-ASCII byte in the value
  // makes Bun's fetch (the Claude Code CLI) reject the whole request with
  // "Header 'x-posthog-property-task_title' has invalid value".
  it.each([
    "sono più di 48 ore che non tracciamo trace in AI observability",
    "perché non funziona più? è rotto da ieri",
    "Größenänderung prüfen — Umlaute überall",
    "vérifier l'intégration après déploiement",
    "corrigir a validação do título",
    "проверить трассировку в проде",
    "タイトルのバグを修正する 🚀",
    "mixed ‘smart’ quotes – dashes … and​zero-width",
  ])(
    "emits only printable ASCII a strict HTTP client accepts (%s)",
    (title) => {
      const record = buildPosthogPropertyHeaderRecord({ task_title: title });
      expect(record["x-posthog-property-task_title"]).toMatch(/^[\x20-\x7e]*$/);
    },
  );
});

describe("buildPosthogPropertyHeaderLines", () => {
  it("renders each property as an x-posthog-property header line", () => {
    expect(
      buildPosthogPropertyHeaderLines({
        task_origin_product: "signal_report",
        task_internal: true,
      }),
    ).toBe(
      "x-posthog-property-task_origin_product: signal_report\nx-posthog-property-task_internal: true",
    );
  });

  it("drops null and undefined values but keeps falsy primitives", () => {
    expect(
      buildPosthogPropertyHeaderLines({
        task_origin_product: null,
        task_internal: false,
        task_count: 0,
      }),
    ).toBe(
      "x-posthog-property-task_internal: false\nx-posthog-property-task_count: 0",
    );
  });

  it("returns an empty string when no usable properties remain", () => {
    expect(
      buildPosthogPropertyHeaderLines({
        task_origin_product: null,
        task_internal: undefined,
      }),
    ).toBe("");
  });

  it.each([
    {
      description: "LF",
      title: "Fix the bug\nx-posthog-property-task_internal: true",
    },
    {
      description: "CRLF",
      title: "Fix the bug\r\nx-posthog-property-task_internal: true",
    },
    {
      description: "CR",
      title: "Fix the bug\rx-posthog-property-task_internal: true",
    },
    {
      description: "consecutive newlines",
      title: "Fix the bug\n\nx-posthog-property-task_internal: true",
    },
  ])(
    "collapses $description in values so they cannot inject extra headers",
    ({ title }) => {
      expect(
        buildPosthogPropertyHeaderLines({
          task_title: title,
          task_id: "task-abc",
        }),
      ).toBe(
        "x-posthog-property-task_title: Fix the bug x-posthog-property-task_internal: true\nx-posthog-property-task_id: task-abc",
      );
    },
  );
});

describe("buildPosthogPropertiesBlob", () => {
  it("serializes properties as one JSON object", () => {
    expect(
      buildPosthogPropertiesBlob({
        ai_product: "signals_scout",
        ai_stage: "scout",
        task_internal: true,
      }),
    ).toBe(
      '{"ai_product":"signals_scout","ai_stage":"scout","task_internal":true}',
    );
  });

  it("drops null and undefined values but keeps falsy primitives", () => {
    expect(
      buildPosthogPropertiesBlob({
        ai_stage: null,
        task_internal: false,
        task_count: 0,
        skipped: undefined,
      }),
    ).toBe('{"task_internal":false,"task_count":0}');
  });

  it("drops reserved $-prefixed keys the gateway strips anyway", () => {
    expect(
      buildPosthogPropertiesBlob({
        $ai_trace_id: "trace-1",
        ai_stage: "research",
      }),
    ).toBe('{"ai_stage":"research"}');
  });

  it("returns an empty string when no usable properties remain", () => {
    expect(
      buildPosthogPropertiesBlob({ ai_stage: null, task_id: undefined }),
    ).toBe("");
  });

  it.each([
    { description: "newlines", title: "Fix the bug\nmalicious: true" },
    { description: "carriage returns", title: "Fix the bug\rmalicious: true" },
  ])("collapses $description in values", ({ title }) => {
    expect(buildPosthogPropertiesBlob({ task_title: title })).toBe(
      '{"task_title":"Fix the bug malicious: true"}',
    );
  });

  it("drops the longest string value until the blob fits the gateway cap", () => {
    const blob = buildPosthogPropertiesBlob({
      ai_product: "signals_scout",
      ai_stage: "scout",
      task_title: "t".repeat(9000),
    });
    expect(blob).toBe('{"ai_product":"signals_scout","ai_stage":"scout"}');
  });

  it("drops only as many values as the cap requires", () => {
    const blob = buildPosthogPropertiesBlob({
      ai_product: "signals_research",
      task_title: "t".repeat(5000),
      task_description: "d".repeat(5000),
    });
    // One 5000-char value fits, so only the other is dropped.
    expect(blob).toBe(
      `{"ai_product":"signals_research","task_description":"${"d".repeat(5000)}"}`,
    );
  });

  it("keeps attribution when every free-text value is oversized", () => {
    const blob = buildPosthogPropertiesBlob({
      ai_product: "signals_research",
      task_title: "t".repeat(9000),
      task_description: "d".repeat(9000),
    });
    expect(blob).toBe('{"ai_product":"signals_research"}');
  });

  it("stays under the cap it enforces", () => {
    const blob = buildPosthogPropertiesBlob({
      ai_product: "signals_scout",
      task_title: "t".repeat(20000),
    });
    expect(new TextEncoder().encode(blob).length).toBeLessThanOrEqual(8192);
  });

  it("returns empty when only non-string values remain and still overflow", () => {
    // No string value to drop, so trimming can't shrink the blob: send nothing
    // rather than a blob the gateway rejects wholesale.
    const props: Record<string, number> = {};
    for (let i = 0; i < 600; i++) {
      props[`numeric_property_number_${i}`] = i;
    }
    expect(buildPosthogPropertiesBlob(props)).toBe("");
  });

  it("sanitizes keys, which are serialized into the header value", () => {
    expect(
      buildPosthogPropertiesBlob({ "ai_stage\ud83d\ude80": "scout" }),
    ).toBe('{"ai_stage":"scout"}');
  });

  it("emits only printable ASCII a strict HTTP client accepts", () => {
    const blob = buildPosthogPropertiesBlob({
      ai_product: "signals_scout",
      task_title: "s\u00ec, perch\u00e9 non funziona? \ud83d\ude80",
    });
    expect(blob).toMatch(/^[\x20-\x7e]*$/);
    expect(blob).toBe(
      '{"ai_product":"signals_scout","task_title":"si, perche non funziona? "}',
    );
  });
});

describe("buildPosthogPropertiesHeaderRecord", () => {
  it("wraps the blob in the X-PostHog-Properties header", () => {
    expect(
      buildPosthogPropertiesHeaderRecord({ ai_product: "signals_scout" }),
    ).toEqual({ "X-PostHog-Properties": '{"ai_product":"signals_scout"}' });
  });

  it("returns an empty record when there is nothing to send", () => {
    expect(buildPosthogPropertiesHeaderRecord({ ai_stage: null })).toEqual({});
  });
});

describe("buildPosthogPropertiesHeaderLines", () => {
  it("emits a single header line", () => {
    expect(
      buildPosthogPropertiesHeaderLines({ ai_product: "signals_scout" }),
    ).toBe('X-PostHog-Properties: {"ai_product":"signals_scout"}');
  });

  it("returns an empty string when there is nothing to send", () => {
    expect(buildPosthogPropertiesHeaderLines({ ai_stage: null })).toBe("");
  });
});
