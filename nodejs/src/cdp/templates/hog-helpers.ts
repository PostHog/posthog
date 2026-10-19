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
// public, so a frame line carries only code location: the last three path segments, the line and the
// function name. It never reads code_variables or source context, which can hold user data or secrets.
// Each frames[i] read makes the VM measure the whole array. To stay inside the execution time limit, the
// loop reads at most the last 50 frames and skips stacks over 2000 frames. The try block keeps a bad trace
// from losing the ticket.
export const hogErrorTrackingStacktraceFn = `fun errorTrackingFramePath(source) {
  let path := splitByString('#', splitByString('?', replaceAll(source, '\\\\', '/'))[1])[1]
  let parts := splitByString('/', path)
  let count := length(parts)
  if (count <= 3) {
    return path
  }
  return concat(parts[count - 2], '/', parts[count - 1], '/', parts[count])
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
        let line := '  File "unknown"'
        if (notEmpty(frame.source)) {
          line := concat('  File "', errorTrackingFramePath(frame.source), '"')
        }
        if (notEmpty(frame.line)) {
          line := concat(line, ', line: ', frame.line)
        }
        let name := frame.resolved_name ?? frame.mangled_name
        if (notEmpty(name)) {
          line := concat(line, ', in: ', name)
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
