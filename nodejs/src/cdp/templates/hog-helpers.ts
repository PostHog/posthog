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

// Frames are stored oldest first, so the loop walks back from the crash site. It keeps only resolved
// in-app frames, because a JS frame without a source map stays minified and library frames push the
// app's own code out of the 10.
export const hogErrorTrackingStacktraceFn = `fun errorTrackingStacktrace(exceptionList) {
  let frames := exceptionList[1].stacktrace.frames
  if (empty(frames)) {
    return ''
  }
  let lines := []
  for (let i := length(frames); i >= 1 and length(lines) < 10; i := i - 1) {
    let frame := frames[i]
    if (frame.resolved and frame.in_app) {
      let line := concat('  File "', frame.source ?? 'Unknown source', '"')
      if (notEmpty(frame.line)) {
        line := concat(line, ', line: ', frame.line)
      }
      let name := frame.resolved_name ?? frame.mangled_name
      if (notEmpty(name)) {
        line := concat(line, ', in: ', name)
      }
      lines := arrayPushBack(lines, line)
    }
  }
  if (empty(lines)) {
    return ''
  }
  return concat('\\n\\n\`\`\`\\n', arrayStringConcat(lines, '\\n'), '\\n\`\`\`')
}`
