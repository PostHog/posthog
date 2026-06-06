// react-markdown v9 depends on unified v11 which uses a CallableInstance
// pattern that breaks under Sucrase's .call(void 0) transform in Jest.
// This mock provides a lightweight replacement that renders markdown children
// as plain text, which is sufficient for component tests.

const React = require('react')

function ReactMarkdown({ children }) {
    return React.createElement('div', { 'data-testid': 'react-markdown' }, children)
}

ReactMarkdown.defaultProps = {}

module.exports = ReactMarkdown
module.exports.default = ReactMarkdown
