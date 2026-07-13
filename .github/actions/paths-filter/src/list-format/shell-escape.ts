// Backslash escape every character except small subset of definitely safe characters
export function backslashEscape(value: string): string {
  return value.replace(/([^a-zA-Z0-9,._+:@%/-])/gm, '\\$1')
}

// Returns filename escaped for usage as shell argument.
// Applies "human readable" approach with as few escaping applied as possible
export function shellEscape(value: string): string {
  if (value === '') return value

  // Only safe characters
  if (/^[a-zA-Z0-9,._+:@%/-]+$/m.test(value)) {
    return value
  }

  if (value.includes("'")) {
    // Only safe characters, single quotes and white-spaces
    if (/^[a-zA-Z0-9,._+:@%/'\s-]+$/m.test(value)) {
      return `"${value}"`
    }

    // Split by single quote and apply escaping recursively
    return value.split("'").map(shellEscape).join("\\'")
  }

  // Contains some unsafe characters but no single quote
  return `'${value}'`
}
