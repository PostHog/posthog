import { describe, expect, it } from "vitest";
import {
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
