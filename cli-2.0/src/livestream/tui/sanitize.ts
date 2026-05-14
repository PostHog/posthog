/**
 * Strip ANSI escape sequences and terminal control characters from untrusted input.
 * Prevents terminal injection attacks from malicious event data.
 */
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]|\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\].*?(?:\x07|\x1B\\))/g

export const sanitize = (input: unknown): string => {
  if (input === null) return 'null'
  if (input === undefined) return 'undefined'
  const str = typeof input === 'string' ? input : String(input)
  return str.replace(CONTROL_CHARS, '')
}

export const sanitizeJson = (value: unknown): string => {
  const json = JSON.stringify(value, null, 2)
  return sanitize(json)
}
