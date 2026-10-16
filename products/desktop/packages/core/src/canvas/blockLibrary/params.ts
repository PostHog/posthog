const PARAM_KINDS = [
  "text",
  "longtext",
  "number",
  "boolean",
  "select",
  "event",
  "events",
  "property",
  "insight",
  "color",
] as const;

export type ParamKind = (typeof PARAM_KINDS)[number];

export interface ParamOption {
  value: string;
  label: string;
}

export interface ParamSpec {
  kind: ParamKind;
  label: string;
  description: string | null;
  options: ParamOption[];
  min: number | null;
  max: number | null;
  step: number | null;
  fallback: unknown;
}

export type ParamSchema = Array<{ name: string; spec: ParamSpec }>;

const KINDS = new Set<string>(PARAM_KINDS);

export function componentLabel(name: string): string {
  const spaced = name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parseOptions(value: unknown): ParamOption[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((option): ParamOption[] => {
    if (typeof option === "string") return [{ value: option, label: option }];
    if (option && typeof option === "object" && "value" in option) {
      const record = option as { value: unknown; label?: unknown };
      const optionValue = String(record.value);
      return [
        {
          value: optionValue,
          label: typeof record.label === "string" ? record.label : optionValue,
        },
      ];
    }
    return [];
  });
}

function parseSpec(name: string, raw: unknown): ParamSpec | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const kind = (record.type ?? record.kind) as ParamKind;
  if (!KINDS.has(kind)) return null;
  return {
    kind,
    label:
      typeof record.label === "string" ? record.label : componentLabel(name),
    description:
      typeof record.description === "string" ? record.description : null,
    options: parseOptions(record.options),
    min: numberOrNull(record.min),
    max: numberOrNull(record.max),
    step: numberOrNull(record.step),
    fallback: record.default,
  };
}

export function parseParamSchema(raw: string | null): ParamSchema | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
      return null;
    const schema = Object.entries(parsed as Record<string, unknown>).flatMap(
      ([name, spec]) => {
        const parsedSpec = parseSpec(name, spec);
        return parsedSpec ? [{ name, spec: parsedSpec }] : [];
      },
    );
    return schema.length > 0 ? schema : null;
  } catch {
    return null;
  }
}
