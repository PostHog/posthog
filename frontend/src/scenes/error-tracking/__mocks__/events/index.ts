import javascript_empty from './javascript_empty.json'
import javascript_resolved from './javascript_resolved.json'
import node_unresolved from './node_unresolved.json'
import python_resolved from './python_resolved.json'

export const TEST_EVENTS = {
    javascript_empty: javascript_empty,
    javascript_resolved: javascript_resolved,
    node_unresolved: node_unresolved,
    python_resolved: python_resolved,
}

export type TestEventNames = keyof typeof TEST_EVENTS
