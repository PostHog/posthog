/**
 * Hog snippets shared across templates. Prepended into a template's `code`, so the functions
 * they define are callable from the rest of that template's Hog source.
 */

/**
 * Pulls the human-readable message out of a PostHog API error response, so a failing template
 * surfaces "Invalid API key" rather than a bare status code. Falls back to the whole body for
 * responses that don't use either of our standard error shapes.
 */
export const hogApiErrorMessageFn = `fun apiErrorMessage(response) {
  return response.body.error ?? response.body.detail ?? response.body
}`

// Ticket trackers sit outside PostHog's access controls, and a GitHub or GitLab repository can be
// public, so a frame line carries only a file name, the line and the function name. Cymbal marks a JS
// frame without a source map as resolved, and an inline script's source is the page URL, which can end
// in a token. So a file name shows only when it looks like a source file, and a function name only when
// it uses identifier characters. Anything else, or any name that holds a UUID or a key-shaped run of
// letters and digits, becomes [redacted]. The function
// never reads code_variables or source context, which can hold user data or secrets.
// Each frames[i] read makes the VM measure the whole array. To stay inside the execution time limit, the
// loop reads at most the last 50 frames and skips stacks over 2000 frames. The try block keeps a bad trace
// from losing the ticket.
export const hogErrorTrackingStacktraceFn = `fun errorTrackingHasSecret(text) {
  if (match(text, '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')) {
    return true
  }
  let parts := text
  for (let separator in ['_', '-', '.', '$', ':', '<', '>', '(', ')', '#', ',', '[', ']', ' ', '+', '=']) {
    parts := replaceAll(parts, separator, '/')
  }
  for (let part in splitByString('/', parts)) {
    if (length(part) >= 16 and match(part, '[0-9]')) {
      return true
    }
  }
  return false
}

fun errorTrackingFunctionName(name) {
  let text := toString(name)
  if (not match(text, '^[]A-Za-z0-9_$.:<>()#,[ -]{1,100}$') or errorTrackingHasSecret(text)) {
    return '[redacted]'
  }
  return text
}

fun errorTrackingFileName(source) {
  let path := splitByString('#', splitByString('?', replaceAll(toString(source), '\\\\', '/'))[1])[1]
  let parts := splitByString('/', path)
  let name := parts[length(parts)]
  if (not match(name, '^[A-Za-z0-9_.-]{1,64}[.](js|mjs|cjs|jsx|ts|tsx|mts|cts|vue|svelte|py|rb|php|go|java|kt|kts|scala|rs|swift|dart|ex|exs|erl|cs|c|cc|cpp|h|hpp|m|mm|lua)$')) {
    return '[redacted]'
  }
  return errorTrackingHasSecret(name) ? '[redacted]' : name
}

fun errorTrackingStacktrace(exceptionList) {
  try {
    let frames := exceptionList[1].stacktrace.frames
    let last := length(frames)
    if (empty(frames) or last > 2000) {
      return ''
    }
    let lines := []
    let first := last > 50 ? last - 49 : 1
    for (let i := last; i >= first and length(lines) < 5; i := i - 1) {
      let frame := frames[i]
      if (frame.resolved and frame.in_app) {
        let line := concat('  File "', notEmpty(frame.source) ? errorTrackingFileName(frame.source) : 'unknown', '"')
        if (notEmpty(frame.line)) {
          line := concat(line, ', line: ', frame.line)
        }
        let name := frame.resolved_name ?? frame.mangled_name
        if (notEmpty(name)) {
          line := concat(line, ', in: ', errorTrackingFunctionName(name))
        }
        lines := arrayPushBack(lines, replaceAll(substring(line, 1, 200), '\`', '\\''))
      }
    }
    if (empty(lines)) {
      return ''
    }
    return concat('\\n\\n\`\`\`\\n', arrayStringConcat(lines, '\\n'), '\\n\`\`\`')
  } catch (error) {
    return ''
  }
}`
