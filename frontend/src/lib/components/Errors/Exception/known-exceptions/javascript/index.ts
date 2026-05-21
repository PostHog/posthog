// Order matters — the registry returns the first match.
// More specific TypeError handlers (e.g. load-failed) must come before
// the generic TypeError handler.
import './load-failed'
import './non-error-promise-rejection'
import './react-minified-error'
import './script-error'
import './syntax-error'
import './dom-exception'
import './type-error'
import './range-error'
