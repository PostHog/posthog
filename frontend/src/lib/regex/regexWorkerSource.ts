// Keep this program fixed: patterns and subjects cross postMessage only as data.
export const REGEX_WORKER_SOURCE = `
self.onmessage = function(event) {
    var results = event.data.checks.map(function(check) {
        try {
            return { matches: new RegExp(check.pattern, check.flags).test(check.subject) };
        } catch (error) {
            if (error instanceof SyntaxError) { return { error: 'syntax_error' }; }
            throw error;
        }
    });
    self.postMessage({ type: 'result', results: results });
};
self.postMessage({ type: 'ready' });
`
