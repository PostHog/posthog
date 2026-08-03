import type { SessionConfigOption } from "@agentclientprotocol/sdk";

type RawOptionItem = {
  value?: string;
  options?: Array<{ value: string }>;
};

export function flattenConfigValues(option: SessionConfigOption): string[] {
  if (option.type !== "select") return [];
  return (option.options as RawOptionItem[]).flatMap((o) =>
    o.options ? o.options.map((g) => g.value) : o.value ? [o.value] : [],
  );
}

export function isValidConfigValue(
  option: SessionConfigOption | undefined,
  value: string,
): option is Extract<SessionConfigOption, { type: "select" }> {
  if (!option || option.type !== "select") return false;
  return flattenConfigValues(option).includes(value);
}
