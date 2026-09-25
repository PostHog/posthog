import type {
  SourceConfig,
  SourceFieldConfig,
  SourceFieldInputConfig,
  SourceFieldSelectConfig,
} from "@posthog/api-client/posthog-client";

export type FieldValue = string | number | boolean | string[];
export type FieldValues = Record<string, FieldValue>;

const INPUT_TYPES = new Set([
  "text",
  "email",
  "search",
  "url",
  "password",
  "time",
  "number",
  "textarea",
]);

/** Whether a field is a plain text-like input the generic renderer handles. */
export function isInputField(
  field: SourceFieldConfig,
): field is SourceFieldInputConfig {
  return INPUT_TYPES.has(field.type);
}

/**
 * A field type the generic renderer cannot handle inline (SSH tunnels, file
 * uploads). Sources requiring these still need a bespoke form.
 */
export function isUnsupportedField(field: SourceFieldConfig): boolean {
  return field.type === "ssh-tunnel" || field.type === "file-upload";
}

/** The value a select holds, or its default: a list for a `multiple` select, one value otherwise. */
export function selectValue(
  field: SourceFieldSelectConfig,
  values: FieldValues,
): string | string[] {
  const value = values[field.name];
  if (field.multiple) {
    if (Array.isArray(value)) return value;
    return field.defaultValue ? [field.defaultValue] : [];
  }
  return typeof value === "string" ? value : (field.defaultValue ?? "");
}

/**
 * Walk the currently active fields and collect the names of required inputs and
 * selects that are not yet satisfied, so we can gate the submit button and
 * validate before posting. A select with a `defaultValue` is always satisfied,
 * because the control renders that value pre-selected.
 */
export function missingRequiredFields(
  config: SourceConfig,
  values: FieldValues,
): string[] {
  const missing: string[] = [];
  const walk = (fields: SourceFieldConfig[]) => {
    for (const field of fields) {
      if (field.type === "switch-group") {
        if (values[field.name]) walk(field.fields);
      } else if (field.type === "select") {
        const selected = selectValue(field, values);
        // An empty array is truthy, so a multiple select needs its own emptiness check or
        // `required` passes with nothing selected.
        const empty = Array.isArray(selected)
          ? selected.length === 0
          : selected.trim().length === 0;
        if (field.required && empty) {
          missing.push(field.name);
        }
        if (!Array.isArray(selected)) {
          const option = field.options.find((o) => o.value === selected);
          if (option?.fields) walk(option.fields);
        }
      } else if (field.type === "oauth") {
        if (field.required && !values[field.name]) {
          missing.push(field.name);
        }
      } else if (field.type === "oauth-account-select") {
        const value = values[field.name];
        if (
          field.required &&
          (typeof value !== "string" || value.trim().length === 0)
        ) {
          missing.push(field.name);
        }
      } else if (isInputField(field) && field.required) {
        const value = values[field.name];
        if (typeof value !== "string" || value.trim().length === 0) {
          missing.push(field.name);
        }
      }
    }
  };
  walk(config.fields);
  return missing;
}

/**
 * Build the `createExternalDataSource` payload from the collected field values,
 * mirroring how PostHog Cloud nests switch-group and select fields.
 */
export function buildPayload(
  config: SourceConfig,
  values: FieldValues,
): Record<string, unknown> {
  const collect = (fields: SourceFieldConfig[]): Record<string, unknown> => {
    const out: Record<string, unknown> = {};
    for (const field of fields) {
      if (field.type === "switch-group") {
        const enabled = !!values[field.name];
        out[field.name] = { enabled, ...collect(field.fields) };
      } else if (field.type === "select") {
        const selected = selectValue(field, values);
        if (Array.isArray(selected)) {
          out[field.name] = selected;
          continue;
        }
        // A select whose options carry their own fields names a branch, so the branch and its
        // fields nest under `selection`. A plain select submits the bare value.
        const hasOptionFields = field.options.some(
          (o) => (o.fields?.length ?? 0) > 0,
        );
        const option = field.options.find((o) => o.value === selected);
        out[field.name] = hasOptionFields
          ? {
              selection: selected,
              ...(option?.fields ? collect(option.fields) : {}),
            }
          : selected;
      } else if (field.type === "oauth") {
        const value = values[field.name];
        if (value !== undefined && value !== "") out[field.name] = value;
      } else if (field.type === "oauth-account-select") {
        const value = values[field.name];
        if (typeof value === "string" && value.trim() !== "") {
          out[field.name] = value.trim();
        }
      } else if (isInputField(field)) {
        const value = values[field.name];
        if (typeof value === "string") out[field.name] = value.trim();
      }
    }
    return out;
  };
  return collect(config.fields);
}
