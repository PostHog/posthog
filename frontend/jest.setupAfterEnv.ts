import * as React from 'react'

global.React = React

// A require, not an import, because the taxonomy builds JSX and needs the global React set above.
// eslint-disable-next-line @typescript-eslint/no-require-imports
require('~/taxonomy/registerCoreFilterDefinitions')
